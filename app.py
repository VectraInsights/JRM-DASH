import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
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
        b64_key = gs["private_key_base64"]
        key_decoded = base64.b64decode(b64_key).decode("utf-8")
        info["private_key"] = key_decoded.replace("\\n", "\n")
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        client = gspread.authorize(creds)
        return client.open_by_key(ID_PLANILHA).worksheet("Página1")
    except Exception as e:
        st.error(f"❌ Erro Google Sheets: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    refresh_token = str(refresh_token_raw).strip()

    if not refresh_token or len(refresh_token) < 20:
        st.error(f"❌ Refresh Token da {empresa} parece inválido na planilha.")
        return None

    # Tenta renovar com o scope novo caso o anterior tenha sido gerado sem ele
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "openid profile aws.cognito.signin.user.admin"
    }

    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        
        if response.status_code == 200:
            dados = response.json()
            # Salva o novo refresh imediatamente
            novo_refresh = dados.get("refresh_token")
            if novo_refresh:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            
            return dados.get("access_token")
        else:
            st.error(f"❌ Erro na Troca de Token ({empresa})")
            st.code(response.text)
            return None
    except Exception as e:
        st.error(f"❌ Falha de rede: {e}")
        return None

def listar_lancamentos(token, empresa):
    url = "https://api.contaazul.com/v1/financials/transactions"
    headers = {"Authorization": f"Bearer {token}"}
    
    # Datas
    inicio = (datetime.now() - timedelta(days=7)).date().isoformat()
    fim = (datetime.now() + timedelta(days=45)).date().isoformat()
    params = {"expiration_start": inicio, "expiration_end": fim}

    r = requests.get(url, headers=headers, params=params)
    
    if r.status_code == 200:
        res = r.json()
        return res if isinstance(res, list) else res.get('items', [])
    else:
        st.error(f"❌ Erro 401/API na {empresa}: {r.text}")
        return None

# --- UI ---
st.title("📊 Fluxo de Caixa - Depuração")

if st.button('🚀 Sincronizar'):
    aba = conectar_google_sheets()
    dados_planilha = aba.get_all_records()
    
    for row in dados_planilha:
        emp = row['empresa']
        st.subheader(f"Unidade: {emp}")
        
        # 1. PEGA O ACCESS TOKEN
        access = obter_access_token(emp, row['refresh_token'], aba)
        
        if access:
            # 2. USA O ACCESS TOKEN PARA PEGAR DADOS
            itens = listar_lancamentos(access, emp)
            
            if itens is not None:
                st.success(f"✅ {len(itens)} lançamentos obtidos!")
                if len(itens) > 0:
                    st.dataframe(pd.DataFrame(itens)[['due_date', 'description', 'amount']])
            else:
                st.error(f"🚨 O Access Token foi gerado, mas a API de Finanças o rejeitou.")
        else:
            st.error(f"🚨 Falha ao gerar Access Token. Verifique o log acima.")
