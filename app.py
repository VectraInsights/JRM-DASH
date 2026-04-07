import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- CONFIGURAÇÕES (Mantidas) ---
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
    # Endpoint de parcelas da V2
    url = f"https://api-v2.contaazul.com/v1/financeiro/contas-a-{tipo}/parcelas"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # REMOVIDO FILTRO DE DATA: Vamos trazer tudo o que a API permitir (limite de 500)
    params = {"pagina": 1, "tamanho_pagina": 500} 
    
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            return r.json().get("itens", [])
        return []
    except: return []

# --- UI ---
st.set_page_config(page_title="Dashboard Financeiro", layout="wide")
st.title("📊 Resumo Financeiro Consolidado")

if st.button('🚀 Atualizar Dashboard'):
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
                        st.write(f"⚠️ {emp}: Nenhum item retornado para {rotulo}.")
                    
                    for i in itens:
                        # TRATAMENTO DE STATUS: Aceita qualquer coisa que não seja 'QUITADO' ou 'BAIXADO'
                        status = str(i.get('status', '')).upper()
                        if status not in ["QUITADO", "BAIXADO", "PAGO", "RECEBIDO"]:
                            
                            dt_raw = i.get('data_vencimento')
                            dt_venc = pd.to_datetime(dt_raw).date()
                            
                            v = i.get('valor', 0)
                            # Trata se o valor vier como float ou dicionário {'valor': 10.0}
                            val = v.get('valor', 0) if isinstance(v, dict) else v
                            
                            consolidado.append({
                                'data': dt_venc, 
                                'valor': float(val), 
                                'tipo': rotulo, 
                                'unidade': emp,
                                'status_original': status
                            })

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # --- CARDS ---
        tr = df[df['tipo'] == 'Receita']['valor'].sum()
        tp = df[df['tipo'] == 'Despesa']['valor'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("TOTAL A RECEBER", f"R$ {tr:,.2f}")
        c2.metric("TOTAL A PAGAR", f"R$ {tp:,.2f}")
        c3.metric("SALDO LÍQUIDO", f"R$ {(tr - tp):,.2f}")

        # --- GRÁFICO DE BARRAS ---
        st.subheader("📅 Evolução por Data de Vencimento")
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)
        if 'Receita' not in df_g: df_g['Receita'] = 0
        if 'Despesa' not in df_g: df_g['Despesa'] = 0
        
        st.bar_chart(df_g[['Receita', 'Despesa']])

        st.write("### Detalhamento dos Dados")
        st.dataframe(df)
    else:
        st.error("❌ Nenhum dado financeiro em aberto encontrado.")
        st.info("Motivos possíveis: 1. As parcelas estão com status 'Quitado'. 2. O Token não tem permissão para a API V2. 3. Não há lançamentos financeiros criados (apenas Vendas).")
