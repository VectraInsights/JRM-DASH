import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import base64

# --- CONFIGURAÇÕES DA API (MANTENHA EXATAMENTE COMO NO PAINEL DO CONTA AZUL) ---
CLIENT_ID = "SEU_CLIENT_ID"
CLIENT_SECRET = "SEU_CLIENT_SECRET"
# IMPORTANTE: O Refresh Token muda quase sempre que é usado.
REFRESH_TOKEN = "SEU_REFRESH_TOKEN_ATUAL"

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Financeiro Conta Azul", layout="wide")

def renovar_acesso():
    """Troca o Refresh Token por novos Access e Refresh Tokens"""
    url = "https://api.contaazul.com/oauth2/token"
    
    # Criando o cabeçalho Basic Auth manualmente para garantir precisão
    auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": st.session_state.get('refresh_token', REFRESH_TOKEN)
    }

    try:
        response = requests.post(url, data=data, headers=headers)
        res_data = response.json()
        
        if response.status_code == 200:
            # Salvamos ambos na sessão para o app continuar rodando
            st.session_state.access_token = res_data.get("access_token")
            st.session_state.refresh_token = res_data.get("refresh_token")
            return True
        else:
            st.error(f"Erro de Autenticação: {res_data.get('error_description', 'Verifique Client ID e Secret')}")
            return False
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return False

# --- INICIALIZAÇÃO DO TOKEN ---
if 'access_token' not in st.session_state:
    renovar_acesso()

# --- FUNÇÃO DE BUSCA (CONTAS) ---
def buscar_dados(endpoint, d1, d2):
    if 'access_token' not in st.session_state:
        return []
        
    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    params = {"data_vencimento_de": d1, "data_vencimento_ate": d2, "size": 100}
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    
    res = requests.get(url, headers=headers, params=params)
    
    # Se expirar, renova e tenta de novo
    if res.status_code == 401:
        if renovar_acesso():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE ---
st.sidebar.header("📅 Período de Vencimento")
d_ini = st.sidebar.date_input("Início", datetime(2026, 4, 1))
d_fim = st.sidebar.date_input("Fim", datetime(2026, 4, 30))

if st.sidebar.button("📊 Atualizar Dashboard"):
    st.header(f"Resumo Financeiro: {d_ini.strftime('%d/%m')} a {d_fim.strftime('%d/%m')}")
    
    rec = buscar_dados("contas-a-receber", d_ini, d_fim)
    pag = buscar_dados("contas-a-pagar", d_ini, d_fim)
    
    df_rec = pd.DataFrame(rec)
    df_pag = pd.DataFrame(pag)
    
    v_rec = df_rec['value'].sum() if not df_rec.empty else 0
    v_pag = df_pag['value'].sum() if not df_pag.empty else 0
    
    # Cards de Indicadores
    c1, c2, c3 = st.columns(3)
    c1.metric("A Receber", f"R$ {v_rec:,.2f}")
    c2.metric("A Pagar", f"R$ {v_pag:,.2f}", delta_color="inverse")
    c3.metric("Saldo", f"R$ {v_rec - v_pag:,.2f}")
    
    st.divider()
    
    t1, t2 = st.tabs(["Receitas", "Despesas"])
    with t1:
        if not df_rec.empty:
            st.dataframe(df_rec[['customer_name', 'value', 'due_date', 'status']], use_container_width=True)
    with t2:
        if not df_pag.empty:
            st.dataframe(df_pag[['supplier_name', 'value', 'due_date', 'status']], use_container_width=True)
else:
    st.info("Aguardando consulta...")
