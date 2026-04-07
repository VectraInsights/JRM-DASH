import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import base64

# --- 1. CONFIGURAÇÕES E CREDENCIAIS ---
# Conta Azul (Seção [api])
C_ID = st.secrets["api"]["client_id"].strip()
C_SECRET = st.secrets["api"]["client_secret"].strip()

# Google Sheets (Seção [connections.gsheets])
def conectar_google():
    try:
        # Decodifica a chave privada que está em base64 no seu secrets
        decoded_key = base64.b64decode(st.secrets["connections.gsheets"]["private_key_base64"]).decode("utf-8")
        
        info = {
            "type": st.secrets["connections.gsheets"]["type"],
            "project_id": st.secrets["connections.gsheets"]["project_id"],
            "private_key_id": st.secrets["connections.gsheets"]["private_key_id"],
            "private_key": decoded_key,
            "client_email": st.secrets["connections.gsheets"]["client_email"],
            "client_id": st.secrets["connections.gsheets"]["client_id"],
            "auth_uri": st.secrets["connections.gsheets"]["auth_uri"],
            "token_uri": st.secrets["connections.gsheets"]["token_uri"],
            "auth_provider_x509_cert_url": st.secrets["connections.gsheets"]["auth_provider_x509_cert_url"],
            "client_x509_cert_url": st.secrets["connections.gsheets"]["client_x509_cert_url"],
        }
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Erro na conexão com Google: {e}")
        return None

# --- 2. GESTÃO DE TOKENS (PLANILHA) ---
def gerenciar_token(novo_token=None):
    client = conectar_google()
    if not client: return None
    
    try:
        # Abre a planilha pelo nome exato: Tokens_ContaAzul
        sh = client.open("Tokens_ContaAzul")
        ws = sh.worksheet("Tokens")
        
        if novo_token:
            # Atualiza a célula B2 (Coluna refresh_token, linha JTL)
            ws.update_acell('B2', novo_token)
            return novo_token
        else:
            # Lê o valor atual da célula B2
            return ws.acell('B2').value
    except Exception as e:
        st.error(f"Erro ao acessar aba 'Tokens': {e}")
        return None

# --- 3. LOGICA API CONTA AZUL ---
def renovar_acesso_ca():
    url = "https://api.contaazul.com/oauth2/token"
    refresh_atual = gerenciar_token()
    
    if not refresh_atual:
        st.error("Não foi possível ler o Refresh Token da planilha.")
        return False
        
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_atual.strip()
    }

    try:
        # Autenticação via Basic Auth
        res = requests.post(url, data=payload, auth=(C_ID, C_SECRET))
        
        if res.status_code == 200:
            dados = res.json()
            # Salva o NOVO refresh_token de volta na planilha
            gerenciar_token(novo_token=dados.get("refresh_token"))
            st.session_state.access_token = dados.get("access_token")
            return True
        else:
            st.error(f"Erro API (Status {res.status_code}): {res.text}")
            return False
    except Exception as e:
        st.error(f"Falha na renovação: {e}")
        return False

def buscar_v1(endpoint, d1, d2):
    if 'access_token' not in st.session_state:
        if not renovar_acesso_ca(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {"data_vencimento_de": d1, "data_vencimento_ate": d2, "size": 100}

    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 401:
        if renovar_acesso_ca():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- 4. INTERFACE STREAMLIT ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("📊 Painel Financeiro - Integração JTL")

with st.sidebar:
    st.header("Configurações")
    data_ini = st.date_input("Vencimento De", datetime(2026, 4, 1))
    data_fim = st.date_input("Vencimento Até", datetime(2026, 4, 30))
    if st.button("🚀 Sincronizar Agora"):
        st.session_state.clicou = True

if st.session_state.get('clicou'):
    with st.spinner("Conectando ao Google Sheets e Conta Azul..."):
        r = buscar_v1("contas-a-receber", data_ini, data_fim)
        p = buscar_v1("contas-a-pagar", data_ini, data_fim)

        if r or p:
            df_r = pd.DataFrame(r)
            df_p = pd.DataFrame(p)
            
            c1, c2, c3 = st.columns(3)
            val_r = df_r['value'].sum() if not df_r.empty else 0
            val_p = df_p['value'].sum() if not df_p.empty else 0
            
            c1.metric("Receitas", f"R$ {val_r:,.2f}")
            c2.metric("Despesas", f"R$ {val_p:,.2f}", delta_color="inverse")
            c3.metric("Saldo Líquido", f"R$ {val_r - val_p:,.2f}")
            
            st.divider()
            t1, t2 = st.tabs(["Contas a Receber", "Contas a Pagar"])
            with t1: st.dataframe(df_r, use_container_width=True)
            with t2: st.dataframe(df_p, use_container_width=True)
        else:
            st.warning("Nenhum dado encontrado no período selecionado.")
