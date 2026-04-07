import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime

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
    except: return None

def buscar_parcelas_v2(token, tipo):
    url = f"https://api-v2.contaazul.com/v1/financeiro/contas-a-{tipo}/parcelas"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"pagina": 1, "tamanho_pagina": 100} 
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            return r.json().get("itens", [])
        return []
    except: return []

# --- UI ---
st.set_page_config(page_title="Dashboard Financeiro", layout="wide")
st.title("📊 Totais Financeiros e Gráfico")

if st.button('🚀 Rodar Varredura'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        
        if token:
            with st.status(f"Lendo {emp}...", expanded=False):
                for tipo_api, rotulo in [("receber", "Receita"), ("pagar", "Despesa")]:
                    itens = buscar_parcelas_v2(token, tipo_api)
                    
                    if not itens:
                        st.warning(f"A API não retornou parcelas de {rotulo} para {emp}.")
                        continue

                    for i in itens:
                        status = str(i.get('status', '')).upper()
                        
                        # Filtro: Ignora apenas o que está liquidado (PAGO/QUITADO/RECEBIDO)
                        if status not in ["QUITADO", "PAGO", "RECEBIDO", "BAIXADO"]:
                            
                            # Captura de Valor (V2 multi-formato)
                            v_raw = i.get('valor')
                            if isinstance(v_raw, dict):
                                val = v_raw.get('valor', 0)
                            else:
                                val = i.get('valor_nominal', i.get('valor', 0))

                            dt_venc = pd.to_datetime(i.get('data_vencimento')).date()
                            
                            consolidado.append({
                                'data': dt_venc, 
                                'valor': float(val), 
                                'tipo': rotulo, 
                                'unidade': emp
                            })

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # --- TOTAIS ---
        tr = df[df['tipo'] == 'Receita']['valor'].sum()
        tp = df[df['tipo'] == 'Despesa']['valor'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("TOTAL A RECEBER", f"R$ {tr:,.2f}")
        c2.metric("TOTAL A PAGAR", f"R$ {tp:,.2f}")
        c3.metric("SALDO EM ABERTO", f"R$ {(tr - tp):,.2f}")

        # --- GRÁFICO ---
        st.subheader("📅 Gráfico de Vencimentos")
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)
        # Garante que as colunas existam para o gráfico não quebrar
        for col in ['Receita', 'Despesa']:
            if col not in df_g.columns: df_g[col] = 0
            
        st.bar_chart(df_g[['Receita', 'Despesa']])
        
        with st.expander("Ver lista de itens"):
            st.write(df)
    else:
        st.error("Nenhum dado encontrado. Verifique se os lançamentos financeiros existem no Conta Azul.")
