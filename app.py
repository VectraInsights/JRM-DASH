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
URL_BASE_V2 = "https://api-v2.contaazul.com"

def conectar_google_sheets():
    try:
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
    except Exception as e:
        st.error(f"Erro Google: {e}"); st.stop()

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
        return None
    except: return None

def buscar_financeiro_v2(token, tipo_evento):
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    hoje = datetime.now()
    params = {
        "pagina": 1, "tamanho_pagina": 1000,
        "data_vencimento_de": hoje.strftime("%Y-%m-%d"),
        "data_vencimento_ate": (hoje + timedelta(days=30)).strftime("%Y-%m-%d"),
        "status": "EM_ABERTO"
    }
    try:
        r = requests.get(endpoint, headers=headers, params=params)
        return r.json().get("itens", []) if r.status_code == 200 else []
    except: return []

# --- UI ---
st.set_page_config(page_title="Resumo Financeiro 30D", layout="wide")
st.title("📈 Tendência de Caixa (Próximos 30 Dias)")

if st.button('🚀 Atualizar Indicadores'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    with st.spinner("Sincronizando dados..."):
        for row in linhas:
            emp = row['empresa']
            token = obter_access_token(emp, row['refresh_token'], aba)
            if token:
                for t in ["contas-a-pagar", "contas-a-receber"]:
                    dados = buscar_financeiro_v2(token, t)
                    tipo_label = "Receber" if "receber" in t else "Pagar"
                    for i in dados:
                        # CORREÇÃO DO VALOR: Tentando campos comuns na V2
                        valor = i.get('valor_total_liquido') or i.get('valor') or i.get('valor_previsto') or 0
                        consolidado.append({
                            'data': i.get('data_vencimento'),
                            'valor': float(valor),
                            'tipo': tipo_label,
                            'unidade': emp
                        })

    if consolidado:
        df = pd.DataFrame(consolidado)
        df['data'] = pd.to_datetime(df['data'])
        
        # MÉTRICAS
        st.divider()
        c1, c2, c3 = st.columns(3)
        rec = df[df['tipo'] == 'Receber']['valor'].sum()
        pag = df[df['tipo'] == 'Pagar']['valor'].sum()
        c1.metric("Recebimentos (30d)", f"R$ {rec:,.2f}")
        c2.metric("Pagamentos (30d)", f"R$ {pag:,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(rec - pag):,.2f}", delta=f"{rec-pag:,.2f}")

        # GRÁFICO DE TENDÊNCIA
        st.subheader("📊 Evolução Diária do Fluxo")
        
        # Agrupar por dia e tipo
        df_diario = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        
        # Garantir que ambas as colunas existam
        for col in ['Receber', 'Pagar']:
            if col not in df_diario.columns: df_diario[col] = 0
            
        df_diario['Saldo Diário'] = df_diario['Receber'] - df_diario['Pagar']
        df_diario['Saldo Acumulado'] = df_diario['Saldo Diário'].cumsum()

        # Plotar gráfico de linha (Tendência Acumulada)
        st.line_chart(df_diario.set_index('data')[['Saldo Acumulado', 'Receber', 'Pagar']])

    else:
        st.warning("Nenhum lançamento encontrado para os próximos 30 dias.")
