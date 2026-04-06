import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES BÁSICAS ---
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit?gid=0#gid=0"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

# --- FUNÇÃO DE CONEXÃO (LIMPEZA DE CHAVE) ---
def conectar_google_sheets():
    # 1. Pega os dados brutos do Secrets
    info = dict(st.secrets["connections"]["gsheets"])
    
    # 2. Limpeza profunda da Private Key
    # Remove espaços, aspas extras e converte \n literal em quebra de linha
    raw_key = info["private_key"].strip().strip("'").strip('"')
    info["private_key"] = raw_key.replace("\\n", "\n")
    
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    try:
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_url(URL_PLANILHA).sheet1
    except Exception as e:
        st.error(f"Erro Crítico na Chave Google: {e}")
        st.stop()

# --- FUNÇÕES CONTA AZUL ---
def obter_access_token(empresa, refresh_token, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Atualiza a planilha na hora
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        return None
    except:
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

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard BPO", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    aba = conectar_google_sheets()
    
    try:
        # Lê os tokens atuais da planilha
        dados_planilha = aba.get_all_records()
        df_tokens = pd.DataFrame(dados_planilha)
    except Exception as e:
        st.error(f"Erro ao ler dados da planilha: {e}")
        st.stop()

    todos_dados = []
    progresso = st.progress(0)
    
    for i, row in df_tokens.iterrows():
        empresa = row['empresa']
        token_atual = row['refresh_token']
        
        with st.spinner(f'Processando {empresa}...'):
            acc_token = obter_access_token(empresa, token_atual, aba)
            if acc_token:
                importados = listar_lancamentos(acc_token)
                for item in importados:
                    item['origem_empresa'] = empresa
                    item['value'] = float(item.get('value', 0))
                todos_dados.extend(importados)
            else:
                st.warning(f"⚠️ {empresa}: Token inválido ou expirado.")
        
        progresso.progress((i + 1) / len(df_tokens))

    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ Sucesso! {len(df_final)} lançamentos importados.")
        st.dataframe(df_final, use_container_width=True)
    else:
        st.error("Nenhum dado pôde ser coletado. Verifique os tokens na planilha.")
else:
    st.info("Clique no botão para iniciar a sincronização.")
