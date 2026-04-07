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

def buscar_financeiro(token, endpoint_path):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    hoje = datetime.now()
    params = {
        "pagina": 1, "tamanho_pagina": 1000,
        "data_vencimento_de": hoje.strftime("%Y-%m-%d"),
        "data_vencimento_ate": (hoje + timedelta(days=30)).strftime("%Y-%m-%d"),
        "status": "EM_ABERTO"
    }
    try:
        r = requests.get(f"{URL_BASE_V2}/v1/financeiro/{endpoint_path}/buscar", headers=headers, params=params)
        return r.json().get("itens", []) if r.status_code == 200 else []
    except: return []

# --- APP ---
st.set_page_config(page_title="Resumo 30D", layout="wide")
st.title("📈 Projeção de Caixa (Próximos 30 Dias)")

if st.button('🚀 Atualizar Totais'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    dados_brutos = []

    with st.spinner("Processando unidades..."):
        for row in linhas:
            emp = row['empresa']
            token = obter_access_token(emp, row['refresh_token'], aba)
            if token:
                # Receitas
                rec = buscar_financeiro(token, "contas-a-receber")
                for i in rec:
                    # Na V2, valor pode vir como float ou dict {'valor': 0.0}
                    v = i.get('valor')
                    valor_final = v.get('valor', 0) if isinstance(v, dict) else (v or 0)
                    dados_brutos.append({'data': i.get('data_vencimento'), 'valor': float(valor_final), 'tipo': 'Receber'})
                
                # Despesas
                pag = buscar_financeiro(token, "contas-a-pagar")
                for i in pag:
                    v = i.get('valor')
                    valor_final = v.get('valor', 0) if isinstance(v, dict) else (v or 0)
                    dados_brutos.append({'data': i.get('data_vencimento'), 'valor': float(valor_final), 'tipo': 'Pagar'})

    if dados_brutos:
        df = pd.DataFrame(dados_brutos)
        df['data'] = pd.to_datetime(df['data'])
        
        # Totais
        total_r = df[df['tipo'] == 'Receber']['valor'].sum()
        total_p = df[df['tipo'] == 'Pagar']['valor'].sum()

        st.divider()
        col1, col2, col3 = st.columns(3)
        col1.metric("Total a Receber", f"R$ {total_r:,.2f}")
        col2.metric("Total a Pagar", f"R$ {total_p:,.2f}")
        col3.metric("Saldo Líquido", f"R$ {(total_r - total_p):,.2f}")

        # Gráfico de Tendência
        st.subheader("📊 Tendência Acumulada do Período")
        df_agrupado = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        
        # Garantir colunas para o gráfico
        if 'Receber' not in df_agrupado: df_agrupado['Receber'] = 0
        if 'Pagar' not in df_agrupado: df_agrupado['Pagar'] = 0
        
        df_agrupado = df_agrupado.sort_values('data')
        df_agrupado['Saldo Diário'] = df_agrupado['Receber'] - df_agrupado['Pagar']
        df_agrupado['Saldo Acumulado'] = df_agrupado['Saldo Diário'].cumsum()
        
        # Plot
        st.area_chart(df_agrupado.set_index('data')[['Saldo Acumulado']])
    else:
        st.info("Nenhum lançamento em aberto para os próximos 30 dias.")
