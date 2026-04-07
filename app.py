import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- CARREGAMENTO DOS SECRETS CONFORME SEU ARQUIVO ---
# Note que estamos buscando dentro de ["api"] e não ["contaazul"]
try:
    CLIENT_ID = st.secrets["api"]["client_id"].strip()
    CLIENT_SECRET = st.secrets["api"]["client_secret"].strip()
    
    # IMPORTANTE: Você precisa adicionar o refresh_token na seção [api] do seu secrets!
    # Vou tentar pegar da seção [api], se não existir, mostro um erro amigável.
    if "refresh_token" in st.secrets["api"]:
        REFRESH_TOKEN_INI = st.secrets["api"]["refresh_token"].strip()
    else:
        st.error("ERRO: 'refresh_token' não encontrado na seção [api] do seu Secrets.")
        st.stop()
except KeyError as e:
    st.error(f"Erro ao ler segredos: A chave {e} não foi encontrada na seção [api].")
    st.stop()

# --- CONFIGURAÇÃO DO APP ---
st.set_page_config(page_title="Dashboard JRM - Financeiro", layout="wide")

def renovar_token():
    url = "https://api.contaazul.com/oauth2/token"
    token_atual = st.session_state.get('refresh_token', REFRESH_TOKEN_INI)
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": token_atual
    }

    try:
        # Autenticação via Header (Basic Auth)
        response = requests.post(url, data=payload, auth=(CLIENT_ID, CLIENT_SECRET))
        
        if response.status_code == 200:
            dados = response.json()
            st.session_state.access_token = dados.get("access_token")
            st.session_state.refresh_token = dados.get("refresh_token")
            return True
        else:
            erro = response.json().get('error_description', response.text)
            st.error(f"Falha na Autenticação API: {erro}")
            return False
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return False

def buscar_dados(endpoint, d1, d2):
    if 'access_token' not in st.session_state:
        if not renovar_token(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {"data_vencimento_de": d1, "data_vencimento_ate": d2, "size": 100}

    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 401:
        if renovar_token():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE ---
st.title("📊 Painel Financeiro - Conta Azul")

with st.sidebar:
    st.header("Período")
    d_ini = st.date_input("Início", datetime(2026, 4, 1))
    d_fim = st.date_input("Fim", datetime(2026, 4, 30))
    consultar = st.button("Sincronizar Dados")

if consultar:
    with st.spinner("Consultando API..."):
        dados_rec = buscar_dados("contas-a-receber", d_ini, d_fim)
        dados_pag = buscar_dados("contas-a-pagar", d_ini, d_fim)

        if dados_rec or dados_pag:
            df_rec = pd.DataFrame(dados_rec)
            df_pag = pd.DataFrame(dados_pag)
            
            c1, c2, c3 = st.columns(3)
            v_rec = df_rec['value'].sum() if not df_rec.empty else 0
            v_pag = df_pag['value'].sum() if not df_pag.empty else 0
            
            c1.metric("Receber", f"R$ {v_rec:,.2f}")
            c2.metric("Pagar", f"R$ {v_pag:,.2f}", delta_color="inverse")
            c3.metric("Saldo", f"R$ {v_rec - v_pag:,.2f}")
            
            st.divider()
            t1, t2 = st.tabs(["Receitas", "Despesas"])
            with t1: st.dataframe(df_rec, use_container_width=True)
            with t2: st.dataframe(df_pag, use_container_width=True)
        else:
            st.warning("Nenhum dado encontrado.")
