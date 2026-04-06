import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
# Use o link direto sem o gid=0 no final para evitar confusão de abas
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit"
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
        
        # Decodifica a chave Base64 que enviamos antes
        b64_key = gs["private_key_base64"]
        key_decoded = base64.b64decode(b64_key).decode("utf-8")
        info["private_key"] = key_decoded.replace("\\n", "\n")

        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        
        # ACESSO À ABA ESPECÍFICA: "Página1" (conforme sua imagem)
        spreadsheet = client.open_by_url(URL_PLANILHA)
        return spreadsheet.worksheet("Página1")
        
    except gspread.exceptions.SpreadsheetNotFound:
        st.error("❌ Planilha não encontrada! Verifique se a URL está correta.")
        st.stop()
    except gspread.exceptions.WorksheetNotFound:
        st.error("❌ A aba 'Página1' não foi encontrada! Verifique o nome na parte inferior da planilha.")
        st.stop()
    except Exception as e:
        st.error(f"❌ Erro de Conexão: {e}")
        st.info("💡 Verifique se você compartilhou a planilha com o e-mail da Service Account como EDITOR.")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Procura a empresa na Coluna A e atualiza o token na Coluna B
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
        return r.json().get('items', []) if r.status_code == 200 else []
    except:
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("🏢 Sincronizador Multi-CNPJ JRM")

if st.button('🚀 Sincronizar Agora'):
    aba = conectar_google_sheets()
    
    with st.status("Lendo dados da 'Página1'...", expanded=True) as status:
        # Lê todos os registros (empresa, refresh_token)
        registros = aba.get_all_records()
        if not registros:
            st.error("A planilha parece estar vazia ou os cabeçalhos estão incorretos.")
            st.stop()
            
        df_tokens = pd.DataFrame(registros)
        todos_dados = []
        
        for _, row in df_tokens.iterrows():
            emp_nome = row['empresa']
            st.write(f"🔄 Conectando: **{emp_nome}**")
            
            token = obter_access_token(emp_nome, row['refresh_token'], aba)
            if token:
                vendas = listar_lancamentos(token)
                for v in vendas:
                    v['empresa_origem'] = emp_nome
                todos_dados.extend(vendas)
            else:
                st.warning(f"⚠️ Não foi possível renovar o token para: {emp_nome}")
        
        status.update(label="Processamento Finalizado!", state="complete")

    if todos_dados:
        st.success(f"Sucesso! {len(todos_dados)} lançamentos carregados.")
        st.dataframe(pd.DataFrame(todos_dados), use_container_width=True)
    else:
        st.info("Nenhum dado encontrado para os últimos 30 dias.")
