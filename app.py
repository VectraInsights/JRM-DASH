import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit?gid=0#gid=0"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    """Conecta ao Sheets decodificando a chave de Base64 para evitar erros PEM."""
    try:
        gs = st.secrets["connections"]["gsheets"]
        
        # Reconstrói o dicionário de credenciais
        info = {
            "type": gs["type"],
            "project_id": gs["project_id"],
            "private_key_id": gs["private_key_id"],
            "client_email": gs["client_email"],
            "client_id": gs["client_id"],
            "auth_uri": gs["auth_uri"],
            "token_uri": gs["token_uri"],
            "auth_provider_x509_cert_url": gs["auth_provider_x509_cert_url"],
            "client_x509_cert_url": gs["client_x509_cert_url"]
        }
        
        # DECODIFICAÇÃO SEGURA
        b64_key = gs["private_key_base64"]
        # Decodifica o Base64 e trata quebras de linha
        key_decoded = base64.b64decode(b64_key).decode("utf-8")
        # Garante que \n de texto vire quebra de linha real
        info["private_key"] = key_decoded.replace("\\n", "\n")

        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_url(URL_PLANILHA).sheet1
    except Exception as e:
        st.error(f"❌ Erro de Conexão: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    """Renova o token na Conta Azul."""
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Atualiza na Col B (assumindo Empresa na A e Token na B)
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        return None
    except:
        return None

def listar_lancamentos(access_token):
    """Busca transações dos últimos 30 dias."""
    url = "https://api.contaazul.com/v1/financials/transactions"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "expiration_start": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "expiration_end": datetime.now().date().isoformat()
    }
    try:
        r = requests.get(url, headers=headers, params=params)
        return r.json().get('items', []) if r.status_code == 200 else []
    except:
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("🏢 Sincronizador de Dados - JRM")

if st.button('🚀 Iniciar Sincronização'):
    aba = conectar_google_sheets()
    
    with st.status("Lendo planilha e tokens...", expanded=True) as status:
        df_tokens = pd.DataFrame(aba.get_all_records())
        todos_dados = []
        
        for _, row in df_tokens.iterrows():
            empresa = row['empresa']
            st.write(f"🔄 Processando: **{empresa}**")
            
            token = obter_access_token(empresa, row['refresh_token'], aba)
            if token:
                vendas = listar_lancamentos(token)
                for v in vendas:
                    v['empresa_origem'] = empresa
                todos_dados.extend(vendas)
            else:
                st.warning(f"⚠️ Erro no token da {empresa}")
        
        status.update(label="Sincronização Finalizada!", state="complete")

    if todos_dados:
        st.subheader("Dados Consolidados")
        st.dataframe(pd.DataFrame(todos_dados), use_container_width=True)
    else:
        st.info("Nenhum dado novo encontrado.")
