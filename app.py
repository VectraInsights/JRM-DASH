import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- CARREGAMENTO SEGURO DOS SECRETS ---
# Certifique-se de que no seu arquivo (ou no Cloud) esteja assim:
# [contaazul]
# client_id = "seu_id"
# client_secret = "seu_secret"
# refresh_token = "seu_refresh"

CLIENT_ID = st.secrets["contaazul"]["client_id"].strip()
CLIENT_SECRET = st.secrets["contaazul"]["client_secret"].strip()

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Financeiro Conta Azul", layout="wide")

def renovar_token_v1():
    """Lógica de refresh usando as credenciais do Secrets"""
    url = "https://api.contaazul.com/oauth2/token"
    
    # O Refresh Token inicial vem do secret, mas os próximos vêm da sessão
    token_para_atualizar = st.session_state.get('refresh_token', st.secrets["contaazul"]["refresh_token"])
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": token_para_atualizar.strip()
    }

    try:
        # A API do Conta Azul prefere o Basic Auth explícito no cabeçalho
        # O parâmetro 'auth' do requests faz exatamente isso:
        response = requests.post(url, data=payload, auth=(CLIENT_ID, CLIENT_SECRET))
        
        if response.status_code == 200:
            dados = response.json()
            st.session_state.access_token = dados.get("access_token")
            st.session_state.refresh_token = dados.get("refresh_token")
            return True
        else:
            # Mostra o erro exato para diagnóstico
            st.error(f"Erro na Autenticação (Secrets): {response.json().get('error_description', response.text)}")
            return False
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return False

# --- BUSCA DE DADOS (CONTAS A PAGAR / RECEBER) ---
def buscar_dados(endpoint, d1, d2):
    if 'access_token' not in st.session_state:
        if not renovar_token_v1(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {
        "data_vencimento_de": d1, 
        "data_vencimento_ate": d2,
        "size": 100
    }

    res = requests.get(url, headers=headers, params=params)
    
    # Se o Access Token expirou (401), tenta renovar automaticamente
    if res.status_code == 401:
        if renovar_token_v1():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE ---
st.title("💰 Gestão de Contas (Cabeçalhos)")

with st.sidebar:
    st.header("Filtros")
    data_ini = st.date_input("Vencimento De", datetime(2026, 4, 1))
    data_fim = st.date_input("Vencimento Até", datetime(2026, 4, 30))
    if st.button("🚀 Sincronizar Agora"):
        st.session_state.clicou = True

if st.session_state.get('clicou'):
    with st.spinner("Buscando dados no Conta Azul..."):
        rec = buscar_dados("contas-a-receber", data_ini, data_fim)
        pag = buscar_dados("contas-a-pagar", data_ini, data_fim)

        if rec or pag:
            # Cálculos de Dashboard
            df_rec = pd.DataFrame(rec)
            df_pag = pd.DataFrame(pag)
            
            v_rec = df_rec['value'].sum() if not df_rec.empty else 0
            v_pag = df_pag['value'].sum() if not df_pag.empty else 0
            
            c1, c2, c3 = st.columns(3)
            c1.metric("A Receber", f"R$ {v_rec:,.2f}")
            c2.metric("A Pagar", f"R$ {v_pag:,.2f}", delta_color="inverse")
            c3.metric("Saldo Previsto", f"R$ {v_rec - v_pag:,.2f}")
            
            st.divider()
            
            t1, t2 = st.tabs(["Receitas", "Despesas"])
            with t1:
                if not df_rec.empty:
                    st.dataframe(df_rec[['customer_name', 'value', 'due_date', 'status']], use_container_width=True)
            with t2:
                if not df_pag.empty:
                    st.dataframe(df_pag[['supplier_name', 'value', 'due_date', 'status']], use_container_width=True)
        else:
            st.warning("Verifique as mensagens de erro ou as datas selecionadas.")
