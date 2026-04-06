import streamlit as st
import requests
import pandas as pd
import base64
from datetime import datetime, timedelta

# 1. CONFIGURAÇÕES DOS SEGREDOS
# Certifique-se que no seu Secrets do Streamlit as chaves estão exatamente com estes nomes
CLIENT_ID = st.secrets["client_id"]
CLIENT_SECRET = st.secrets["client_secret"]
TOKENS_LIST = st.secrets["refresh_tokens"] # Deve ser uma lista: ["token1", "token2"...]

def obter_access_token(refresh_token):
    """Renova o access_token usando o refresh_token."""
    url = "https://auth.contaazul.com/oauth2/token"
    
    # O Conta Azul exige Basic Auth (ID:Secret em base64) ou auth=(id, secret)
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    try:
        # Usando auth=(id, secret) que o requests converte automaticamente para Basic Auth
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            # Log de erro detalhado para debugar no Streamlit
            st.error(f"Erro Autenticação (Status {response.status_code}): {response.text}")
            return None
    except Exception as e:
        st.error(f"Erro de conexão na autenticação: {e}")
        return None

def listar_lancamentos(access_token):
    """Busca os lançamentos financeiros da API."""
    # Endpoint de transações (mais adequado para o DataFrame que o cash-flow)
    url = "https://api.contaazul.com/v1/financials/transactions"
    
    params = {
        # Buscando os últimos 30 dias
        "expiration_start": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "expiration_end": datetime.now().date().isoformat()
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            dados = response.json()
            # A API retorna uma lista ou um dicionário com a chave 'items'
            return dados if isinstance(dados, list) else dados.get('items', [])
        else:
            st.warning(f"Erro ao buscar dados (Status {response.status_code}): {response.text}")
            return []
    except Exception as e:
        st.error(f"Erro na requisição de dados: {e}")
        return []

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Dashboard BPO Financeiro", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    todos_dados = []
    progresso = st.progress(0)
    
    for i, token in enumerate(TOKENS_LIST):
        nome_empresa = f"Empresa {i+1}"
        with st.spinner(f'Sincronizando {nome_empresa}...'):
            
            # Passo 1: Pegar Token de Acesso
            acc_token = obter_access_token(token)
            
            if acc_token:
                # Passo 2: Pegar Lançamentos
                dados_empresa = listar_lancamentos(acc_token)
                
                if dados_empresa:
                    # Normaliza os dados e identifica a origem
                    for item in dados_empresa:
                        item['origem_empresa'] = nome_empresa
                        # Garante que campos numéricos sejam floats para o pandas
                        item['value'] = float(item.get('value', 0))
                    
                    todos_dados.extend(dados_empresa)
                else:
                    st.info(f"💡 {nome_empresa}: Conectada, mas sem lançamentos no período.")
            else:
                st.error(f"❌ {nome_empresa}: Falha na conexão. Verifique o Refresh Token.")
        
        # Atualiza barra de progresso
        progresso.progress((i + 1) / len(TOKENS_LIST))

    # --- EXIBIÇÃO DOS RESULTADOS ---
    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ Sucesso! {len(df_final)} lançamentos consolidados.")
        
        # Layout de Colunas para Métricas
        col1, col2 = st.columns(2)
        
        with col1:
            # Filtro Multi-seleção
            empresas_selecionadas = st.multiselect(
                "Filtrar por Empresa", 
                df_final['origem_empresa'].unique(), 
                default=df_final['origem_empresa'].unique()
            )
            df_filtrado = df_final[df_final['origem_empresa'].isin(empresas_selecionadas)]
        
        with col2:
            # Cálculo de Valor Total (considerando a coluna 'value' da API)
            if 'value' in df_filtrado.columns:
                total_geral = df_filtrado['value'].sum()
                st.metric("Total Movimentado (Período)", f"R$ {total_geral:,.2f}")

        # Tabela Principal
        st.subheader("Extrato Consolidado")
        st.dataframe(df_filtrado, use_container_width=True)
        
    else:
        st.error("Nenhum dado foi coletado. Verifique as mensagens de erro acima para cada empresa.")

else:
    st.info("Clique no botão acima para iniciar a coleta de dados via API.")
