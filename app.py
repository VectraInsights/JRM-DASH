import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES DOS SECRETS ---
# Certifique-se de que no Streamlit Cloud > Settings > Secrets os nomes estejam EXATAMENTE assim:
# client_id = "..."
# client_secret = "..."
# refresh_token = "..."

CLIENT_ID = st.secrets["client_id"]
CLIENT_SECRET = st.secrets["client_secret"]
REFRESH_TOKEN = st.secrets["refresh_token"]

# --- 2. FUNÇÕES DE CONEXÃO ---

def atualizar_token():
    """Troca o Refresh Token por um Access Token válido (Usa auth.contaazul.com)"""
    url = "https://auth.contaazul.com/oauth2/token"
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN
    }
    
    try:
        # Autenticação Basic usando ID e Secret
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        
        if response.status_code == 200:
            return response.json().get("access_token")
        else:
            st.error(f"Erro na renovação do token: {response.text}")
            return None
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return None

def listar_lancamentos(access_token):
    """Busca o fluxo de caixa (cash-flow) dos últimos 30 dias"""
    url = "https://api.contaazul.com/v1/financials/cash-flow"
    
    # Datas obrigatórias para evitar erro 400/401 em alguns endpoints
    data_fim = datetime.now().date()
    data_inicio = data_fim - timedelta(days=30)
    
    params = {
        "startDate": data_inicio.isoformat(),
        "endDate": data_fim.isoformat()
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        return response.json()
    elif response.status_code == 401:
        st.warning("⚠️ Erro 401: Token recusado ou permissão insuficiente (Scope).")
        return None
    else:
        st.error(f"Erro na API ({response.status_code}): {response.text}")
        return None

# --- 3. INTERFACE STREAMLIT ---

st.set_page_config(page_title="Dashboard Conta Azul", layout="wide")

st.title("📊 Sincronização Financeira - Conta Azul")
st.markdown("Clique no botão abaixo para buscar os lançamentos dos últimos 30 dias.")

if st.button('🚀 Sincronizar Dados Agora'):
    with st.spinner('Autenticando e coletando dados...'):
        
        # Passo 1: Pegar token novo
        token_acesso = atualizar_token()
        
        if token_acesso:
            # Passo 2: Pegar dados do financeiro
            dados = listar_lancamentos(token_acesso)
            
            if dados:
                # O Conta Azul costuma retornar uma lista de objetos. 
                # Ajustamos para o Pandas conforme a estrutura da API.
                df = pd.DataFrame(dados)
                
                st.success(f"Conectado! {len(df)} registros encontrados.")
                
                # Exibição
                st.subheader("Extrato de Fluxo de Caixa")
                st.dataframe(df, use_container_width=True)
                
                # Métricas Rápidas
                col1, col2 = st.columns(2)
                
                # Tenta somar a coluna 'value' se ela existir
                if 'value' in df.columns:
                    total_vol = df['value'].sum()
                    col1.metric("Volume Total (30 dias)", f"R$ {total_vol:,.2f}")
                
                if 'type' in df.columns:
                    entradas = len(df[df['type'] == 'INCOME']) if 'INCOME' in df['type'].values else 0
                    col2.metric("Qtd. de Entradas", entradas)
                    
            elif dados == []:
                st.info("A conexão funcionou, mas não há lançamentos neste período.")
        else:
            st.error("Não foi possível validar seu acesso. Verifique o Client ID e Secret.")

---

### Verificação Final nos Secrets (Streamlit Cloud):

Para este código rodar sem erro de "Key", deixe o seu painel de **Secrets** exatamente assim:

```toml
client_id = "5s7uj52d63o8jtsgf89ihjqrgc"
client_secret = "uipuq731ercpsj7hba8npnolb3ubf12u79eumt6kbdqumlvqvk7"
refresh_token = "COLE_AQUI_O_TOKEN_LONGO_QUE_GERAMOS"
