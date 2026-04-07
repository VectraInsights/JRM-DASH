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

def obter_access_token(empresa, refresh_token_raw):
    url = "https://auth.contaazul.com/oauth2/token"
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
            "grant_type": "refresh_token", 
            "refresh_token": str(refresh_token_raw).strip(),
            "scope": "openid profile aws.cognito.signin.user.admin"
        })
        return response.json().get("access_token") if response.status_code == 200 else None
    except: return None

def buscar_dados(token, tipo):
    url = f"https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-{tipo}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "pagina": 1, "tamanho_pagina": 1000,
        "data_vencimento_de": "2025-01-01T00:00:00Z",
        "data_vencimento_ate": "2027-12-31T23:59:59Z"
    }
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 200:
        res = r.json()
        return res.get("items", res.get("itens", []))
    return []

# --- INTERFACE ---
st.title("📊 Dashboard Financeiro (JTL)")

if st.button('🚀 Executar Varredura'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'])
        
        if token:
            with st.status(f"Buscando dados de {emp}...") as s:
                for t, label in [("receber", "Receita"), ("pagar", "Despesa")]:
                    itens = buscar_dados(token, t)
                    
                    # LOG DE DIAGNÓSTICO
                    st.write(f"🔍 {label}: {len(itens)} itens encontrados.")
                    
                    for i in itens:
                        # Tenta pegar o valor de várias formas possíveis na API
                        v_bruto = i.get('valor_nominal') or i.get('valor') or i.get('valor_total', 0)
                        
                        # Se o valor for um dicionário (comum na API V1), pega a chave 'valor'
                        if isinstance(v_bruto, dict):
                            val = v_bruto.get('valor', 0)
                        else:
                            val = v_bruto

                        # Filtro de Status
                        status = str(i.get('status', '')).upper()
                        if status not in ["QUITADO", "PAGO", "RECEBIDO", "BAIXADO"]:
                            consolidado.append({
                                'data': pd.to_datetime(i.get('data_vencimento')).date(),
                                'valor': float(val),
                                'tipo': label,
                                'unidade': emp
                            })
                s.update(label="Varredura completa!", state="complete")

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # Exibição dos Cards
        c1, c2, c3 = st.columns(3)
        rec = df[df['tipo'] == 'Receita']['valor'].sum()
        des = df[df['tipo'] == 'Despesa']['valor'].sum()
        c1.metric("A RECEBER", f"R$ {rec:,.2f}")
        c2.metric("A PAGAR", f"R$ {des:,.2f}")
        c3.metric("SALDO LÍQUIDO", f"R$ {(rec-des):,.2f}")
        
        # Gráfico
        st.subheader("📅 Fluxo de Caixa")
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)
        # Garante colunas para o gráfico não quebrar
        if "Receita" not in df_g.columns: df_g["Receita"] = 0
        if "Despesa" not in df_g.columns: df_g["Despesa"] = 0
        st.bar_chart(df_g[["Receita", "Despesa"]])
        
        # Tabela
        st.write("### Detalhamento")
        st.dataframe(df)
    else:
        st.warning("A API respondeu, mas a lista de itens veio vazia. Verifique se os lançamentos no Conta Azul estão com 'Data de Vencimento' entre 2025 e 2027.")
