import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- CONFIGURAÇÕES (Mantidas do seu original) ---
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

def buscar_parcelas_v2(token, tipo):
    url = f"https://api-v2.contaazul.com/v1/financeiro/contas-a-{tipo}/parcelas"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"pagina": 1, "tamanho_pagina": 500} # Aumentado para pegar mais dados para o gráfico
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
            with st.status(f"Processando {emp}...", expanded=False):
                # Processa Receitas e Despesas
                for tipo_api, rotulo in [("receber", "Receita"), ("pagar", "Despesa")]:
                    itens = buscar_parcelas_v2(token, tipo_api)
                    for i in itens:
                        status = str(i.get('status', '')).upper()
                        # Filtra apenas o que não foi pago ainda
                        if "ABERTO" in status or "PARCIAL" in status or "ATRASADO" in status:
                            dt_venc = pd.to_datetime(i.get('data_vencimento'))
                            v = i.get('valor', 0)
                            val = v.get('valor', 0) if isinstance(v, dict) else v
                            consolidado.append({
                                'data': dt_venc.date(), 
                                'valor': float(val), 
                                'tipo': rotulo, 
                                'unidade': emp
                            })

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # --- CARDS DE TOTAIS ---
        total_receita = df[df['tipo'] == 'Receita']['valor'].sum()
        total_despesa = df[df['tipo'] == 'Despesa']['valor'].sum()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("TOTAL A RECEBER", f"R$ {total_receita:,.2f}")
        col2.metric("TOTAL A PAGAR", f"R$ {total_despesa:,.2f}", delta_color="inverse")
        col3.metric("SALDO EM ABERTO", f"R$ {(total_receita - total_despesa):,.2f}")

        st.divider()

        # --- GRÁFICO ---
        st.subheader("📅 Projeção de Fluxo de Caixa por Data")
        # Agrupa por data e tipo para o gráfico de barras
        df_chart = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)
        
        # Garante que as colunas existam para evitar erro no gráfico
        if 'Receita' not in df_chart: df_chart['Receita'] = 0
        if 'Despesa' not in df_chart: df_chart['Despesa'] = 0
        
        # Exibe gráfico de barras comparativo
        st.bar_chart(df_chart[['Receita', 'Despesa']])

        # --- TABELA DETALHADA ---
        with st.expander("Ver lançamentos detalhados"):
            st.dataframe(df.sort_values(by='data'), use_container_width=True)
    else:
        st.warning("Nenhum dado financeiro em aberto encontrado nas empresas listadas.")
