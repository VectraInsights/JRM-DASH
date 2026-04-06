import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta

# 1. CONFIGURAÇÕES
CLIENT_ID = st.secrets["client_id"]
CLIENT_SECRET = st.secrets["client_secret"]
TOKENS_LIST = st.secrets["refresh_tokens"] # Agora é uma lista

def obter_access_token(refresh_token):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        return response.json().get("access_token") if response.status_code == 200 else None
    except:
        return None

def listar_lancamentos(access_token):
    url = "https://api.contaazul.com/v1/financials/cash-flow"
    params = {
        "startDate": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "endDate": datetime.now().date().isoformat()
    }
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    response = requests.get(url, headers=headers, params=params)
    return response.json() if response.status_code == 200 else []

# INTERFACE
st.set_page_config(page_title="Dashboard Consolidado", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ (Consolidado)")

if st.button('🚀 Sincronizar Todas as Empresas'):
    todos_dados = []
    progresso = st.progress(0)
    
    for i, token in enumerate(TOKENS_LIST):
        with st.spinner(f'Coletando dados da Empresa {i+1}...'):
            acc_token = obter_access_token(token)
            if acc_token:
                dados_empresa = listar_lancamentos(acc_token)
                if dados_empresa:
                    # Adiciona uma coluna para identificar de qual CNPJ vem o dado
                    for item in dados_empresa:
                        item['empresa_id'] = f"CNPJ {i+1}"
                    todos_dados.extend(dados_empresa)
        progresso.progress((i + 1) / len(TOKENS_LIST))

    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"Sucesso! Total de {len(df_final)} lançamentos consolidados.")
        
        # Filtro por Empresa
        empresas = st.multiselect("Filtrar por Empresa", df_final['empresa_id'].unique(), default=df_final['empresa_id'].unique())
        df_filtrado = df_final[df_final['empresa_id'].isin(empresas)]
        
        # Exibição
        st.dataframe(df_filtrado, use_container_width=True)
        
        # Métrica Totalizadora
        if 'value' in df_filtrado.columns:
            total_geral = df_filtrado['value'].sum()
            st.metric("Caixa Total Consolidado", f"R$ {total_geral:,.2f}")
    else:
        st.error("Não foi possível coletar dados de nenhuma empresa. Verifique os Refresh Tokens.")
