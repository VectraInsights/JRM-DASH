import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection

# --- 1. CONFIGURAÇÕES DOS SEGREDOS E CONEXÃO ---
# Pegamos os dados do segredo e limpamos a private_key manualmente para evitar erros de formatação
gsheets_secrets = st.secrets["connections"]["gsheets"]

creds_dict = {
    "type": gsheets_secrets["type"],
    "project_id": gsheets_secrets["project_id"],
    "private_key_id": gsheets_secrets["private_key_id"],
    "private_key": gsheets_secrets["private_key"].replace("\\n", "\n"),
    "client_email": gsheets_secrets["client_email"],
    "client_id": gsheets_secrets["client_id"],
    "auth_uri": gsheets_secrets["auth_uri"],
    "token_uri": gsheets_secrets["token_uri"],
    "auth_provider_x509_cert_url": gsheets_secrets["auth_provider_x509_cert_url"],
    "client_x509_cert_url": gsheets_secrets["client_x509_cert_url"]
}

# Inicializa a conexão com os dados tratados
conn = st.connection("gsheets", type=GSheetsConnection, **creds_dict)

CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

# --- 2. FUNÇÕES DE SUPORTE ---
def atualizar_token_na_planilha(df_completo, nome_empresa, novo_token):
    df_completo.loc[df_completo['empresa'] == nome_empresa, 'refresh_token'] = novo_token
    conn.update(data=df_completo)

def obter_access_token(nome_empresa, refresh_token, df_completo):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            atualizar_token_na_planilha(df_completo, nome_empresa, novo_refresh)
            return dados.get("access_token")
        return None
    except:
        return None

def listar_lancamentos(access_token):
    url = "https://api.contaazul.com/v1/financials/transactions"
    params = {
        "expiration_start": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "expiration_end": datetime.now().date().isoformat()
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            d = r.json()
            return d if isinstance(d, list) else d.get('items', [])
        return []
    except:
        return []

# --- 3. INTERFACE ---
st.set_page_config(page_title="Dashboard BPO", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    try:
        df_tokens = conn.read()
    except Exception as e:
        st.error(f"Erro ao acessar planilha: {e}")
        st.stop()

    todos_dados = []
    progresso = st.progress(0)
    
    for i, row in df_tokens.iterrows():
        nome = row['empresa']
        with st.spinner(f'Processando {nome}...'):
            acc_token = obter_access_token(nome, row['refresh_token'], df_tokens)
            if acc_token:
                dados = listar_lancamentos(acc_token)
                for item in dados:
                    item['origem_empresa'] = nome
                    item['value'] = float(item.get('value', 0))
                todos_dados.extend(dados)
        progresso.progress((i + 1) / len(df_tokens))

    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ {len(df_final)} lançamentos importados!")
        st.dataframe(df_final, use_container_width=True)
    else:
        st.error("Falha na coleta. Verifique se os tokens na planilha são válidos.")
