import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import base64

# --- CONFIGURAÇÕES ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"

# --- CONEXÃO GOOGLE (USANDO SEUS NOMES DE CHAVES ATUAIS) ---
def conectar_google():
    try:
        # Aqui eu uso os nomes que você já tem no seu Secrets
        # Se sua chave estiver em 'private_key_base64' dentro de 'google', usamos assim:
        # Ajustei para buscar no nível que o Streamlit costuma organizar
        
        # Tenta buscar as credenciais do Google conforme você configurou
        google_secrets = st.secrets["connections"]["gsheets"] # Ajuste para o caminho padrão do Streamlit
        
        key_b64 = google_secrets["private_key_base64"]
        decoded_key = base64.b64decode(key_b64).decode("utf-8")
        
        info = {
            "type": google_secrets["type"],
            "project_id": google_secrets["project_id"],
            "private_key_id": google_secrets["private_key_id"],
            "private_key": decoded_key,
            "client_email": google_secrets["client_email"],
            "client_id": google_secrets["client_id"],
            "auth_uri": google_secrets["auth_uri"],
            "token_uri": google_secrets["token_uri"],
            "auth_provider_x509_cert_url": google_secrets["auth_provider_x509_cert_url"],
            "client_x509_cert_url": google_secrets["client_x509_cert_url"],
        }
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Erro na conexão com Google: {e}")
        return None

# --- GESTÃO DE TOKENS NA PLANILHA ---
def gerenciar_token(novo_token=None):
    client = conectar_google()
    if not client: return None
    
    try:
        sh = client.open_by_key(ID_PLANILHA)
        ws = sh.worksheet("Tokens")
        
        if novo_token:
            ws.update_acell('B2', novo_token)
            return novo_token
        else:
            return ws.acell('B2').value
    except Exception as e:
        st.error(f"Erro ao acessar Planilha (Aba 'Tokens'): {e}")
        return None

# --- LÓGICA CONTA AZUL ---
def renovar_acesso_ca():
    url = "https://api.contaazul.com/oauth2/token"
    refresh_atual = gerenciar_token()
    
    if not refresh_atual: return False
        
    # Usa suas chaves da seção [api]
    c_id = st.secrets["api"]["client_id"].strip()
    c_secret = st.secrets["api"]["client_secret"].strip()
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_atual.strip()
    }

    try:
        res = requests.post(url, data=payload, auth=(c_id, c_secret))
        if res.status_code == 200:
            dados = res.json()
            gerenciar_token(novo_token=dados.get("refresh_token"))
            st.session_state.access_token = dados.get("access_token")
            return True
        else:
            st.error(f"Erro Conta Azul: {res.text}")
            return False
    except Exception as e:
        st.error(f"Falha: {e}")
        return False

# --- BUSCA DE DADOS ---
def buscar_ca(endpoint, d1, d2):
    if 'access_token' not in st.session_state:
        if not renovar_acesso_ca(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {"data_vencimento_de": d1, "data_vencimento_ate": d2}

    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 401:
        if renovar_acesso_ca():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("📊 Dashboard Financeiro JTL")

with st.sidebar:
    st.header("Filtros")
    data_ini = st.date_input("Início", datetime(2026, 4, 1))
    data_fim = st.date_input("Fim", datetime(2026, 4, 30))
    if st.button("Sincronizar"):
        st.session_state.run = True

if st.session_state.get('run'):
    with st.spinner("Buscando dados..."):
        r = buscar_ca("contas-a-receber", data_ini, data_fim)
        p = buscar_ca("contas-a-pagar", data_ini, data_fim)

        if r or p:
            df_r, df_p = pd.DataFrame(r), pd.DataFrame(p)
            c1, c2, c3 = st.columns(3)
            v_r = df_r['value'].sum() if not df_r.empty else 0
            v_p = df_p['value'].sum() if not df_p.empty else 0
            
            c1.metric("Receitas", f"R$ {v_r:,.2f}")
            c2.metric("Despesas", f"R$ {v_p:,.2f}")
            c3.metric("Saldo", f"R$ {v_r - v_p:,.2f}")
            
            st.divider()
            t1, t2 = st.tabs(["Receitas", "Despesas"])
            with t1: st.dataframe(df_r)
            with t2: st.dataframe(df_p)
