import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
# Extraí o ID diretamente da sua imagem para não haver erro de digitação
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    try:
        gs = st.secrets["connections"]["gsheets"]
        
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
        
        # Decodifica a chave Base64
        b64_key = gs["private_key_base64"]
        key_decoded = base64.b64decode(b64_key).decode("utf-8")
        info["private_key"] = key_decoded.replace("\\n", "\n")

        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        
        # Tenta abrir pelo ID (mais seguro que URL)
        spreadsheet = client.open_by_key(ID_PLANILHA)
        
        # Tenta abrir a "Página1" (conforme sua imagem)
        return spreadsheet.worksheet("Página1")
        
    except Exception as e:
        st.error(f"❌ Falha técnica na conexão: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Localiza a célula da empresa para atualizar o token ao lado
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
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("🏢 Sincronizador Multi-CNPJ JRM")

if st.button('🚀 Sincronizar Agora'):
    aba = conectar_google_sheets()
    
    with st.status("Lendo dados da planilha...", expanded=True) as status:
        # Pega todos os valores para evitar erro de cabeçalho
        lista_dados = aba.get_all_records()
        
        if not lista_dados:
            st.error("Nenhum dado encontrado na aba 'Página1'. Verifique se os dados começam na linha 1.")
            st.stop()
            
        todos_lancamentos = []
        for row in lista_dados:
            emp = row['empresa']
            token_ref = row['refresh_token']
            
            st.write(f"🔄 Sincronizando: **{emp}**")
            
            acc_token = obter_access_token(emp, token_ref, aba)
            if acc_token:
                itens = listar_lancamentos(acc_token)
                for i in itens:
                    i['unidade'] = emp
                todos_lancamentos.extend(itens)
            else:
                st.warning(f"⚠️ Erro ao renovar token de {emp}")
        
        status.update(label="Sincronização Finalizada!", state="complete")

    if todos_lancamentos:
        df = pd.DataFrame(todos_lancamentos)
        st.success(f"Foram importados {len(df)} registros.")
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Nenhum lançamento encontrado para o período.")
