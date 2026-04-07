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
    try:
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
    except: pass
    return None

def buscar_tudo_v2(token, path):
    """Busca sem filtros de data na URL para garantir que a API retorne algo"""
    url = f"https://api-v2.contaazul.com/v1/financeiro/{path}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Parâmetros mínimos obrigatórios pela V2
    params = {"pagina": 1, "tamanho_pagina": 1000}
    
    try:
        r = requests.get(url, headers=headers, params=params)
        # Se /buscar falhar, tenta a rota direta
        if r.status_code != 200:
            r = requests.get(url.replace('/buscar', ''), headers=headers, params=params)
        
        return r.json().get("itens", []) if r.status_code == 200 else []
    except:
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Fluxo de Caixa", layout="wide")
st.title("📊 Fluxo de Caixa (Próximos 30 Dias)")

if st.button('🔄 Atualizar Indicadores'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    dados_brutos = []

    # Datas de corte para o filtro manual
    amanha = datetime.now() + timedelta(days=1)
    daqui_30 = datetime.now() + timedelta(days=31)

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        
        if token:
            with st.status(f"Lendo {emp}...", expanded=False):
                # Tenta buscar Receitas e Despesas
                for rota in [("contas-a-receber", "Receita"), ("contas-a-pagar", "Despesa")]:
                    itens = buscar_tudo_v2(token, rota[0])
                    for i in itens:
                        # 1. Filtro de Status (Aberto ou Atrasado para fins de teste)
                        status = i.get('status', '').upper()
                        if status in ['EM_ABERTO', 'ATRASADO', 'RECEBIDO_PARCIAL', 'PAGO_PARCIAL']:
                            
                            # 2. Tratamento da Data
                            dt_venc = pd.to_datetime(i.get('data_vencimento'))
                            
                            # 3. FILTRO: Apenas vencimentos de AMANHÃ em diante
                            if amanha <= dt_venc <= daqui_30:
                                # 4. Tratamento do Valor (V2 costuma usar objeto ou float direto)
                                v = i.get('valor')
                                val_final = v.get('valor', 0) if isinstance(v, dict) else (v or 0)
                                
                                dados_brutos.append({
                                    'data': dt_venc,
                                    'valor': float(val_final),
                                    'tipo': rota[1]
                                })

    if dados_brutos:
        df = pd.DataFrame(dados_brutos)
        
        rec = df[df['tipo'] == 'Receita']['valor'].sum()
        desp = df[df['tipo'] == 'Despesa']['valor'].sum()

        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Recebimentos (30d)", f"R$ {rec:,.2f}")
        c2.metric("Pagamentos (30d)", f"R$ {desp:,.2f}")
        c3.metric("Saldo Projetado", f"R$ {(rec - desp):,.2f}")

        # Gráfico
        st.subheader("Tendência de Caixa")
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        if 'Receita' not in df_g: df_g['Receita'] = 0
        if 'Despesa' not in df_g: df_g['Despesa'] = 0
        
        df_g = df_g.sort_values('data')
        df_g['Acumulado'] = (df_g['Receita'] - df_g['Despesa']).cumsum()
        st.area_chart(df_g.set_index('data')['Acumulado'])
    else:
        st.error("⚠️ Nenhum lançamento futuro encontrado nas APIs.")
        st.info("Dica: Verifique se os lançamentos no Conta Azul possuem 'Data de Vencimento' preenchida e status 'Em Aberto'.")
