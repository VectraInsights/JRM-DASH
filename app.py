import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÕES DA API (PAINEL CONTA AZUL) ---
CLIENT_ID = "SEU_CLIENT_ID"
CLIENT_SECRET = "SEU_CLIENT_SECRET"
# O Refresh Token é o que você já tem guardado
REFRESH_TOKEN_INICIAL = "SEU_REFRESH_TOKEN_ATUAL"

# --- CONFIGURAÇÃO DA PÁGINA STREAMLIT ---
st.set_page_config(page_title="Financeiro Conta Azul", page_icon="📊", layout="wide")

# --- LÓGICA DE AUTENTICAÇÃO (REFRESH) ---
def atualizar_tokens():
    """Troca o Refresh Token por um novo Access Token"""
    url = "https://api.contaazul.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN_INICIAL
    }
    try:
        # A API exige Basic Auth com Client ID e Secret
        response = requests.post(url, data=data, auth=(CLIENT_ID, CLIENT_SECRET))
        if response.status_code == 200:
            res_data = response.json()
            return res_data.get("access_token")
        else:
            st.error(f"Erro ao renovar token: {response.text}")
            return None
    except Exception as e:
        st.error(f"Falha na conexão de auth: {e}")
        return None

# Inicializa o token na sessão do navegador se não existir
if 'access_token' not in st.session_state:
    st.session_state.access_token = atualizar_tokens()

# --- FUNÇÃO DE BUSCA DE DADOS (V1 - CONTAS) ---
def buscar_dados_contaazul(endpoint, dt_inicio, dt_fim):
    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    params = {
        "data_vencimento_de": dt_inicio,
        "data_vencimento_ate": dt_fim,
        "size": 100
    }
    
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    
    res = requests.get(url, headers=headers, params=params)
    
    # Se o token expirou (401), renova e tenta de novo UMA vez
    if res.status_code == 401:
        novo_token = atualizar_tokens()
        if novo_token:
            st.session_state.access_token = novo_token
            headers["Authorization"] = f"Bearer {novo_token}"
            res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 200:
        return res.json()
    return []

# --- INTERFACE DO USUÁRIO ---
st.sidebar.title("Configurações")
st.sidebar.info("O sistema gerencia o Refresh Token automaticamente.")

data_de = st.sidebar.date_input("Data Inicial", datetime(2026, 4, 1))
data_ate = st.sidebar.date_input("Data Final", datetime(2026, 4, 30))

if st.sidebar.button("🔄 Sincronizar Dados"):
    st.title("📈 Análise de Contas (Cabeçalhos)")
    
    with st.spinner("Lendo dados do Conta Azul..."):
        # Chamadas para os endpoints de CONTAS (não parcelas)
        res_receber = buscar_dados_contaazul("contas-a-receber", data_de, data_ate)
        res_pagar = buscar_dados_contaazul("contas-a-pagar", data_de, data_ate)

        df_rec = pd.DataFrame(res_receber)
        df_pag = pd.DataFrame(res_pagar)

        # Métricas de Resumo
        val_rec = df_rec['value'].sum() if not df_rec.empty else 0
        val_pag = df_pag['value'].sum() if not df_pag.empty else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {val_rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {val_pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo do Período", f"R$ {val_rec - val_pag:,.2f}")

        st.divider()

        # Tabelas de Detalhamento
        col_rec, col_pag = st.columns(2)
        
        with col_rec:
            st.subheader("Entradas")
            if not df_rec.empty:
                # Seleciona colunas que existem no objeto de Conta V1
                view_rec = df_rec[['customer_name', 'value', 'due_date', 'status']].copy()
                st.dataframe(view_rec, use_container_width=True)
            else:
                st.write("Sem registros.")

        with col_pag:
            st.subheader("Saídas")
            if not df_pag.empty:
                view_pag = df_pag[['supplier_name', 'value', 'due_date', 'status']].copy()
                st.dataframe(view_pag, use_container_width=True)
            else:
                st.write("Sem registros.")
else:
    st.warning("Clique no botão 'Sincronizar Dados' para carregar a interface.")
