import streamlit as st
import requests
import pandas as pd

# 1. Configurações vindas dos Secrets
# IMPORTANTE: No Streamlit Cloud, preencha os nomes exatamente como abaixo (minúsculo ou maiúsculo)
CLIENT_ID = st.secrets["client_id"]
CLIENT_SECRET = st.secrets["client_secret"]
REFRESH_TOKEN = st.secrets["refresh_token"]

def atualizar_token():
    """Troca o Refresh Token por um Access Token válido"""
    # URL CORRETA: auth.contaazul.com
    url = "https://auth.contaazul.com/oauth2/token"
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN
    }
    
    # O Conta Azul exige Basic Auth com Client ID e Client Secret
    response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=data)
    
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        st.error(f"Erro na renovação do token: {response.text}")
        return None

def listar_lancamentos(access_token):
    """Busca os lançamentos financeiros do Conta Azul"""
    # Endpoint de Extrato (Cash Flow)
    url = "https://api.contaazul.com/v1/financials/cash-flow"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        # A API retorna uma lista de lançamentos
        return response.json()
    else:
        st.error(f"Erro ao buscar dados: {response.status_code}")
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
                # Transforma a lista de JSON em uma tabela do Pandas
                df = pd.DataFrame(dados)
                st.success(f"Sincronizado! {len(df)} lançamentos encontrados.")
                
                # Exibindo os dados
                st.subheader("Lançamentos Financeiros")
                st.dataframe(df, use_container_width=True)
                
                # Cálculo de métrica simples (ajuste 'value' pelo nome da coluna real se necessário)
                if 'value' in df.columns:
                    total = df['value'].sum()
                    st.metric("Volume Total no Período", f"R$ {total:,.2f}")
            else:
                st.warning("Nenhum dado retornado ou a lista está vazia.")
