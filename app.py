import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = "67rc11hjc0qt863nql0b20vjg0"
CLIENT_SECRET = "2pgl713loumm8rl0atfrh9i9ja6oi18l2pmqunjbr66qfiqosg2"

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
            "grant_type": "refresh_token", 
            "refresh_token": str(refresh_token_raw).strip(),
            "scope": "openid profile aws.cognito.signin.user.admin"
        })
        if response.status_code == 200:
            dados = response.json()
            # Se a API enviar um novo Refresh Token, atualiza a planilha automaticamente
            novo_refresh = dados.get("refresh_token")
            if novo_refresh and novo_refresh != refresh_token_raw:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
    except: pass
    return None

def buscar_dados(token, tipo):
    # Endpoint conforme documentação do TI
    url = f"https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-{tipo}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "pagina": 1, "tamanho_pagina": 1000,
        "data_vencimento_de": "2025-01-01T00:00:00Z",
        "data_vencimento_ate": "2027-12-31T23:59:59Z"
    }
    r = requests.get(url, headers=headers, params=params)
    return r.json().get("items", r.json().get("itens", [])) if r.status_code == 200 else []

# --- DASHBOARD ---
st.title("📊 Dashboard Financeiro (JTL)")

if st.button('🚀 Atualizar Dados'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        
        if token:
            with st.spinner(f"Lendo {emp}..."):
                for t, label in [("receber", "Receita"), ("pagar", "Despesa")]:
                    itens = buscar_dados(token, t)
                    for i in itens:
                        if str(i.get('status')).upper() not in ["QUITADO", "PAGO", "RECEBIDO"]:
                            v = i.get('valor', 0)
                            val = v if not isinstance(v, dict) else v.get('valor', 0)
                            consolidado.append({
                                'data': pd.to_datetime(i.get('data_vencimento')).date(),
                                'valor': float(val),
                                'tipo': label,
                                'unidade': emp
                            })

    if consolidado:
        df = pd.DataFrame(consolidado)
        c1, c2, c3 = st.columns(3)
        receita = df[df['tipo'] == 'Receita']['valor'].sum()
        despesa = df[df['tipo'] == 'Despesa']['valor'].sum()
        c1.metric("A RECEBER", f"R$ {receita:,.2f}")
        c2.metric("A PAGAR", f"R$ {despesa:,.2f}")
        c3.metric("SALDO", f"R$ {(receita-despesa):,.2f}")
        
        st.subheader("📅 Fluxo de Caixa")
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)
        st.bar_chart(df_g)
    else:
        st.warning("Nenhum dado encontrado. Verifique se o novo Refresh Token foi colado na planilha.")
