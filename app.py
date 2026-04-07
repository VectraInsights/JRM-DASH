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
    """Conecta ao Google Sheets usando as secrets do Streamlit"""
    try:
        gs = st.secrets["connections"]["gsheets"]
        info = {
            "type": gs["type"],
            "project_id": gs["project_id"],
            "private_key_id": gs["private_key_id"],
            "client_email": gs["client_email"],
            "client_id": gs["client_id"],
            "auth_uri": gs["auth_uri"],
            "token_uri": gs["token_uri"],
            "auth_provider_x509_cert_url": gs["auth_provider_x509_cert_url"],
            "client_x509_cert_url": gs["client_x509_cert_url"]
        }
        # Decodifica a chave privada
        b64_key = gs["private_key_base64"]
        info["private_key"] = base64.b64decode(b64_key).decode("utf-8").replace("\\n", "\n")
        
        creds = Credentials.from_service_account_info(info, scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ])
        client = gspread.authorize(creds)
        return client.open_by_key(ID_PLANILHA).worksheet("Página1")
    except Exception as e:
        st.error(f"Erro na conexão com Google Sheets: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    """Atualiza o token da Conta Azul"""
    url = "https://auth.contaazul.com/oauth2/token"
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
            "grant_type": "refresh_token", 
            "refresh_token": str(refresh_token_raw).strip()
        })
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            if novo_refresh:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        return None
    except:
        return None

def buscar_financeiro_futuro(token, tipo_evento):
    """Busca títulos que vencem de AMANHÃ até +30 dias"""
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Filtro: Amanhã até Daqui a 30 dias
    amanha = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    ate_30d = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    params = {
        "pagina": 1,
        "tamanho_pagina": 1000,
        "data_vencimento_de": amanha,
        "data_vencimento_ate": ate_30d,
        "status": "EM_ABERTO"
    }
    try:
        r = requests.get(endpoint, headers=headers, params=params)
        return r.json().get("itens", []) if r.status_code == 200 else []
    except:
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Fluxo Futuro", layout="wide")
st.title("📈 Projeção de Caixa (Apenas títulos a vencer)")

if st.button('🚀 Atualizar Indicadores'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    with st.spinner("Consultando dados futuros..."):
        for row in linhas:
            emp = row['empresa']
            token = obter_access_token(emp, row['refresh_token'], aba)
            
            if token:
                # Buscar Contas a Pagar e Receber
                for t in ["contas-a-receber", "contas-a-pagar"]:
                    itens = buscar_financeiro_futuro(token, t)
                    label = "Receber" if "receber" in t else "Pagar"
                    
                    for i in itens:
                        # Extração de valor robusta (trata número ou objeto)
                        v_raw = i.get('valor')
                        valor = v_raw.get('valor', 0) if isinstance(v_raw, dict) else (v_raw or 0)
                        
                        consolidado.append({
                            'data': i.get('data_vencimento'),
                            'valor': float(valor),
                            'tipo': label
                        })

    if consolidado:
        df = pd.DataFrame(consolidado)
        df['data'] = pd.to_datetime(df['data'])
        
        # --- MÉTRICAS ---
        st.divider()
        c1, c2, c3 = st.columns(3)
        total_r = df[df['tipo'] == 'Receber']['valor'].sum()
        total_p = df[df['tipo'] == 'Pagar']['valor'].sum()
        
        c1.metric("Total a Receber (Futuro)", f"R$ {total_r:,.2f}")
        c2.metric("Total a Pagar (Futuro)", f"R$ {total_p:,.2f}")
        c3.metric("Saldo do Período", f"R$ {(total_r - total_p):,.2f}", delta=f"{total_r - total_p:,.2f}")

        # --- GRÁFICO ---
        st.subheader("📊 Evolução do Saldo Projetado")
        df_plot = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        
        # Garante que as colunas existam
        if 'Receber' not in df_plot: df_plot['Receber'] = 0
        if 'Pagar' not in df_plot: df_plot['Pagar'] = 0
        
        df_plot = df_plot.sort_values('data')
        df_plot['Saldo_Diario'] = df_plot['Receber'] - df_plot['Pagar']
        df_plot['Saldo_Acumulado'] = df_plot['Saldo_Diario'].cumsum()
        
        st.area_chart(df_plot.set_index('data')[['Saldo_Acumulado']])
    else:
        st.warning("Nenhum lançamento futuro encontrado para os próximos 30 dias.")
