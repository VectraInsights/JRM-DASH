import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- CREDENCIAIS (COPIE E COLE COM ATENÇÃO) ---
# Use .strip() para garantir que espaços acidentais sejam removidos
CLIENT_ID = "SEU_CLIENT_ID_AQUI".strip()
CLIENT_SECRET = "SEU_CLIENT_SECRET_AQUI".strip()
REFRESH_TOKEN_INICIAL = "SEU_REFRESH_TOKEN_AQUI".strip()

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Financeiro Pro", layout="wide")

def renovar_acesso():
    """Tenta renovar o token usando as credenciais fornecidas"""
    url = "https://api.contaazul.com/oauth2/token"
    
    # O Refresh Token que vamos usar (prioriza o que está na memória da sessão)
    token_atual = st.session_state.get('refresh_token', REFRESH_TOKEN_INICIAL)
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": token_atual
    }

    try:
        # Usando a autenticação nativa do Requests (mais seguro)
        response = requests.post(
            url, 
            data=payload, 
            auth=(CLIENT_ID, CLIENT_SECRET)
        )
        
        if response.status_code == 200:
            dados = response.json()
            st.session_state.access_token = dados.get("access_token")
            st.session_state.refresh_token = dados.get("refresh_token")
            return True
        else:
            # Exibe exatamente o que a API respondeu para diagnóstico
            erro_msg = response.json().get('error_description', response.text)
            st.error(f"Falha na Autenticação: {erro_msg}")
            return False
            
    except Exception as e:
        st.error(f"Erro de rede: {e}")
        return False

# --- BUSCA DE DADOS (CONTAS) ---
def buscar_financeiro(endpoint, d_inicio, d_fim):
    if 'access_token' not in st.session_state:
        if not renovar_acesso(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {
        "data_vencimento_de": d_inicio,
        "data_vencimento_ate": d_fim,
        "size": 100
    }

    res = requests.get(url, headers=headers, params=params)
    
    # Se o Access Token expirou (401), tenta renovar uma vez
    if res.status_code == 401:
        if renovar_acesso():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE STREAMLIT ---
st.sidebar.title("⚙️ Painel de Controle")
data_ini = st.sidebar.date_input("Vencimento Inicial", datetime(2026, 4, 1))
data_fim = st.sidebar.date_input("Vencimento Final", datetime(2026, 4, 30))

if st.sidebar.button("📊 SINCRONIZAR"):
    st.title("💰 Fluxo de Caixa Realizado/Previsto")
    
    with st.spinner("Conectando ao Conta Azul..."):
        contas_rec = buscar_financeiro("contas-a-receber", data_ini, data_fim)
        contas_pag = buscar_financeiro("contas-a-pagar", data_ini, data_fim)

        df_rec = pd.DataFrame(contas_rec)
        df_pag = pd.DataFrame(contas_pag)

        # Dashboard de métricas
        c1, c2, c3 = st.columns(3)
        v_rec = df_rec['value'].sum() if not df_rec.empty else 0
        v_pag = df_pag['value'].sum() if not df_pag.empty else 0
        
        c1.metric("Receitas", f"R$ {v_rec:,.2f}")
        c2.metric("Despesas", f"R$ {v_pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo Líquido", f"R$ {v_rec - v_pag:,.2f}")

        # Visualização em Tabelas
        st.divider()
        t1, t2 = st.tabs(["📋 Contas a Receber", "💸 Contas a Pagar"])
        
        with t1:
            if not df_rec.empty:
                st.dataframe(df_rec[['customer_name', 'value', 'due_date', 'status']], use_container_width=True)
        with t2:
            if not df_pag.empty:
                st.dataframe(df_pag[['supplier_name', 'value', 'due_date', 'status']], use_container_width=True)
else:
    st.info("Ajuste o período na barra lateral e clique em Sincronizar.")
