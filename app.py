import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES ---
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit?gid=0#gid=0"

# --- 2. FUNÇÃO DE CONEXÃO DIRETA (O SEGREDO) ---
def conectar_google_sheets():
    # Pega os dados do Secrets
    info = st.secrets["connections"]["gsheets"]
    
    # Corrige a private_key na memória (Troca \\n por \n real)
    info_corrigida = dict(info)
    info_corrigida["private_key"] = info["private_key"].replace("\\n", "\n")
    
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Autenticação nativa do Google
    creds = Credentials.from_service_account_info(info_corrigida, scopes=scopes)
    client = gspread.authorize(creds)
    
    # Abre a planilha pela URL e pega a primeira aba
    return client.open_by_url(URL_PLANILHA).sheet1

# --- 3. FUNÇÕES DA CONTA AZUL ---
def obter_access_token(empresa, refresh_token, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            
            # ATUALIZAÇÃO AUTOMÁTICA NA PLANILHA
            # Procura o nome da empresa na coluna A e atualiza o token na coluna B
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            
            return dados.get("access_token")
        else:
            st.error(f"Erro na {empresa}: {response.text}")
            return None
    except Exception as e:
        st.error(f"Erro de conexão na {empresa}: {e}")
        return None

def listar_lancamentos(access_token):
    url = "https://api.contaazul.com/v1/financials/transactions"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "expiration_start": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "expiration_end": datetime.now().date().isoformat()
    }
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            res = r.json()
            return res if isinstance(res, list) else res.get('items', [])
        return []
    except:
        return []

# --- 4. INTERFACE ---
st.set_page_config(page_title="Dashboard BPO Financeiro", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    try:
        aba = conectar_google_sheets()
        # Lê os dados da aba para um DataFrame
        dados_tokens = aba.get_all_records()
        df_tokens = pd.DataFrame(dados_tokens)
    except Exception as e:
        st.error(f"Erro ao acessar Google Sheets: {e}")
        st.stop()

    todos_dados = []
    progresso = st.progress(0)
    
    for i, row in df_tokens.iterrows():
        empresa = row['empresa']
        token_atual = row['refresh_token']
        
        with st.spinner(f'Sincronizando {empresa}...'):
            acc_token = obter_access_token(empresa, token_atual, aba)
            
            if acc_token:
                lancamentos = listar_lancamentos(acc_token)
                for item in lancamentos:
                    item['origem_empresa'] = empresa
                    item['value'] = float(item.get('value', 0))
                todos_dados.extend(lancamentos)
        
        progresso.progress((i + 1) / len(df_tokens))

    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ Sucesso! {len(df_final)} lançamentos consolidados.")
        st.dataframe(df_final, use_container_width=True)
    else:
        st.warning("Nenhum dado coletado. Verifique os tokens na planilha.")

else:
    st.info("Clique no botão para iniciar a sincronização via Google Sheets.")
