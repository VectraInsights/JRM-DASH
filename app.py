import streamlit as st
import requests
import pandas as pd
import base64
from datetime import datetime

# --- CREDENCIAIS (COPIE DIRETAMENTE DO PAINEL CONTA AZUL) ---
CLIENT_ID = "SEU_CLIENT_ID"
CLIENT_SECRET = "SEU_CLIENT_SECRET"
REFRESH_TOKEN_INICIAL = "SEU_REFRESH_TOKEN"

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard Financeiro", layout="wide")

def atualizar_tokens():
    """Realiza o Refresh do Token com tratamento de erro 'invalid_client'"""
    url = "https://api.contaazul.com/oauth2/token"
    
    # 1. Preparar o cabeçalho Basic Auth (Obrigatório para evitar invalid_client)
    auth_pass = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_encoded = base64.b64encode(auth_pass.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_encoded}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # 2. Usar o refresh token da sessão (se existir) ou o inicial
    token_para_uso = st.session_state.get('refresh_token', REFRESH_TOKEN_INICIAL)
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": token_para_uso
    }

    try:
        response = requests.post(url, data=data, headers=headers)
        res_json = response.json()
        
        if response.status_code == 200:
            # IMPORTANTE: Salvar o novo Refresh Token, pois o antigo pode expirar
            st.session_state.access_token = res_json.get("access_token")
            st.session_state.refresh_token = res_json.get("refresh_token")
            return True
        else:
            st.error(f"Erro Crítico: {res_json.get('error_description')}")
            return False
    except Exception as e:
        st.error(f"Falha na comunicação: {e}")
        return False

# --- LÓGICA DE BUSCA DE CONTAS ---
def buscar_contas(endpoint, d1, d2):
    if 'access_token' not in st.session_state:
        if not atualizar_tokens(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {"data_vencimento_de": d1, "data_vencimento_ate": d2}

    res = requests.get(url, headers=headers, params=params)
    
    # Se o Access Token expirou (401), tenta renovar UMA vez
    if res.status_code == 401:
        if atualizar_tokens():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE STREAMLIT ---
st.sidebar.title("Filtros Financeiros")
d_ini = st.sidebar.date_input("Vencimento De", datetime(2026, 4, 1))
d_fim = st.sidebar.date_input("Vencimento Até", datetime(2026, 4, 30))

if st.sidebar.button("📊 ANALISAR CONTAS"):
    st.subheader(f"Movimentações de {d_ini.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}")
    
    with st.spinner("Acessando Conta Azul..."):
        dados_rec = buscar_contas("contas-a-receber", d_ini, d_fim)
        dados_pag = buscar_contas("contas-a-pagar", d_ini, d_fim)

        df_rec = pd.DataFrame(dados_rec)
        df_pag = pd.DataFrame(dados_pag)

        # Exibição de Métricas
        c1, c2, c3 = st.columns(3)
        total_rec = df_rec['value'].sum() if not df_rec.empty else 0
        total_pag = df_pag['value'].sum() if not df_pag.empty else 0
        
        c1.metric("A Receber", f"R$ {total_rec:,.2f}")
        c2.metric("A Pagar", f"R$ {total_pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo", f"R$ {total_rec - total_pag:,.2f}")

        # Tabelas
        t1, t2 = st.tabs(["Receitas", "Despesas"])
        with t1:
            if not df_rec.empty:
                st.dataframe(df_rec[['customer_name', 'value', 'due_date', 'status']], use_container_width=True)
        with t2:
            if not df_pag.empty:
                st.dataframe(df_pag[['supplier_name', 'value', 'due_date', 'status']], use_container_width=True)
else:
    st.info("Configure as datas e clique em analisar.")
