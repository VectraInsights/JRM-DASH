import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    gs = st.secrets["connections"]["gsheets"]
    info = {
        "type": gs["type"], "project_id": gs["project_id"], "private_key_id": gs["private_key_id"],
        "client_email": gs["client_email"], "client_id": gs["client_id"], "auth_uri": gs["auth_uri"],
        "token_uri": gs["token_uri"], "auth_provider_x509_cert_url": gs["auth_provider_x509_cert_url"],
        "client_x509_cert_url": gs["client_x509_cert_url"]
    }
    b64_key = gs["private_key_base64"]
    info["private_key"] = base64.b64decode(b64_key).decode("utf-8").replace("\\n", "\n")
    creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    return gspread.authorize(creds).open_by_key(ID_PLANILHA).worksheet("Página1")

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
        "grant_type": "refresh_token", "refresh_token": str(refresh_token_raw).strip()
    })
    if response.status_code == 200:
        dados = response.json()
        novo_refresh = dados.get("refresh_token")
        if novo_refresh:
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
        return dados.get("access_token")
    return None

def buscar_dados_v2(token, path):
    # Conforme sua doc: v1/conta-financeira/... ou financeiro/contas-a-receber
    url = f"https://api-v2.contaazul.com/v1/financeiro/{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Datas conforme documentação: ISO date format (YYYY-MM-DD)
    amanha = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    daqui_30 = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    
    params = {
        "pagina": 1,
        "tamanho_pagina": 500, # Aumentado para garantir volume
        "data_vencimento_de": amanha,
        "data_vencimento_ate": daqui_30
    }
    
    try:
        r = requests.get(url, headers=headers, params=params)
        # Se a URL direta não funcionar, a V2 as vezes exige o sufixo /buscar
        if r.status_code != 200:
            r = requests.get(f"{url}/buscar", headers=headers, params=params)
        
        return r.json().get("itens", []) if r.status_code == 200 else []
    except:
        return []

# --- APP ---
st.set_page_config(page_title="Fluxo de Caixa", layout="wide")
st.title("📊 Fluxo de Caixa (Próximos 30 Dias)")

if st.button('🔄 Atualizar Indicadores'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    dados_finais = []

    for row in linhas:
        token = obter_access_token(row['empresa'], row['refresh_token'], aba)
        if token:
            # Receitas
            recs = buscar_dados_v2(token, "contas-a-receber")
            for i in recs:
                if i.get('status') in ['EM_ABERTO', 'RECEBIDO_PARCIAL']: # Filtro manual
                    # Valor na V2 pode ser um campo 'valor' ou 'saldo'
                    val = i.get('valor', 0)
                    if isinstance(val, dict): val = val.get('valor', 0)
                    dados_finais.append({'data': i.get('data_vencimento'), 'valor': float(val), 'tipo': 'Receita'})
            
            # Despesas
            desp = buscar_dados_v2(token, "contas-a-pagar")
            for i in desp:
                if i.get('status') in ['EM_ABERTO', 'RECEBIDO_PARCIAL']:
                    val = i.get('valor', 0)
                    if isinstance(val, dict): val = val.get('valor', 0)
                    dados_finais.append({'data': i.get('data_vencimento'), 'valor': float(val), 'tipo': 'Despesa'})

    if dados_finais:
        df = pd.DataFrame(dados_finais)
        df['data'] = pd.to_datetime(df['data'])
        
        receitas_total = df[df['tipo'] == 'Receita']['valor'].sum()
        despesas_total = df[df['tipo'] == 'Despesa']['valor'].sum()

        col1, col2, col3 = st.columns(3)
        col1.metric("Recebimentos", f"R$ {receitas_total:,.2f}")
        col2.metric("Pagamentos", f"R$ {despesas_total:,.2f}")
        col3.metric("Saldo do Período", f"R$ {(receitas_total - despesas_total):,.2f}")

        # Gráfico
        st.subheader("Tendência Acumulada")
        df_agrupado = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        if 'Receita' not in df_agrupado: df_agrupado['Receita'] = 0
        if 'Despesa' not in df_agrupado: df_agrupado['Despesa'] = 0
        df_agrupado['Saldo'] = (df_agrupado['Receita'] - df_agrupado['Despesa']).cumsum()
        st.line_chart(df_agrupado.set_index('data')['Saldo'])
    else:
        st.warning("Nenhum dado encontrado. Verifique se há contas 'Em Aberto' com vencimento a partir de amanhã.")
