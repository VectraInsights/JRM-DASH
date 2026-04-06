import streamlit as st
import requests
import pandas as pd

# 1. Configurações vindas dos Secrets
CLIENT_ID = st.secrets["client_id"]
CLIENT_SECRET = st.secrets["client_secret"]
# O refresh_token inicial que você já possui
REFRESH_TOKEN = st.secrets["REFRESH_TOKEN"]

def atualizar_token():
    """Troca o Refresh Token por um Access Token válido"""
    url = "https://api.contaazul.com/oauth2/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN
    }
    response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=data)
    
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        st.error(f"Erro na renovação do token: {response.text}")
        return None

def listar_lancamentos(access_token):
    """Busca os lançamentos financeiros do Conta Azul"""
    url = "https://api.contaazul.com/v1/financials/cash-flow"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Exemplo: Pegando lançamentos dos últimos 30 dias
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        return response.json()
    return []

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Dashboard Conta Azul", layout="wide")

st.title("🚀 Sincronização Conta Azul")

if st.button('Sincronizar Dados do ERP'):
    with st.spinner('Conectando ao Conta Azul...'):
        token_valido = atualizar_token()
        
        if token_valido:
            dados = listar_lancamentos(token_valido)
            
            if dados:
                df = pd.DataFrame(dados)
                st.success(f"Sincronizado! {len(df)} lançamentos encontrados.")
                
                # Exibindo os dados
                st.subheader("Lançamentos Financeiros")
                st.dataframe(df, use_container_width=True)
                
                # Exemplo de métrica rápida
                total = df['value'].sum() if 'value' in df.columns else 0
                st.metric("Volume Total no Período", f"R$ {total:,.2f}")
            else:
                st.warning("Nenhum dado retornado para o período.")
