import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import base64
import re

# --- CONFIGURAÇÕES FIXAS ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"

def conectar_google():
    try:
        if "google_sheets" not in st.secrets:
            st.error("Seção [google_sheets] não encontrada no Secrets.")
            return None
            
        google = st.secrets["google_sheets"]
        
        # 1. LIMPEZA TOTAL DO BASE64
        # Remove TUDO que não for letra, número, +, / ou = (limpa aspas, espaços e \n invisíveis)
        b64_raw = str(google["private_key_base64"])
        b64_clean = re.sub(r'[^a-zA-Z0-9+/=]', '', b64_raw)
        
        # 2. DECODIFICAÇÃO
        decoded_bytes = base64.b64decode(b64_clean)
        # 'latin-1' é mais permissivo para evitar erros de codec iniciais
        decoded_str = decoded_bytes.decode("latin-1").strip()
        
        # 3. RECONSTRUÇÃO DA ESTRUTURA PEM
        # Remove qualquer lixo de header que possa ter vindo na string
        core = decoded_str.replace("-----BEGIN PRIVATE KEY-----", "")
        core = core.replace("-----END PRIVATE KEY-----", "")
        core = re.sub(r'\s+', '', core) # Remove qualquer espaço ou quebra de linha interna
        
        # Monta a chave com quebras de linha exatas a cada 64 caracteres (exigência RSA)
        final_key = "-----BEGIN PRIVATE KEY-----\n"
        for i in range(0, len(core), 64):
            final_key += core[i:i+64] + "\n"
        final_key += "-----END PRIVATE KEY-----\n"

        info = {
            "type": google["type"],
            "project_id": google["project_id"],
            "private_key_id": google["private_key_id"],
            "private_key": final_key,
            "client_email": google["client_email"],
            "client_id": google["client_id"],
            "auth_uri": google["auth_uri"],
            "token_uri": google["token_uri"],
            "auth_provider_x509_cert_url": google["auth_provider_x509_cert_url"],
            "client_x509_cert_url": google["client_x509_cert_url"],
        }
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.sidebar.error(f"Erro de Conexão Google: {e}")
        return None

def gerenciar_token(novo_token=None):
    client = conectar_google()
    if not client: return None
    try:
        sh = client.open_by_key(ID_PLANILHA)
        ws = sh.worksheet("Tokens")
        if novo_token:
            ws.update_acell('B2', novo_token)
            return novo_token
        return ws.acell('B2').value
    except Exception as e:
        st.sidebar.error(f"Erro na Planilha: {e}")
        return None

def renovar_acesso_ca():
    refresh_atual = gerenciar_token()
    if not refresh_atual: return False
    
    url = "https://api.contaazul.com/oauth2/token"
    c_id = st.secrets["api"]["client_id"]
    c_secret = st.secrets["api"]["client_secret"]
    
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_atual.strip()}
    
    try:
        res = requests.post(url, data=payload, auth=(c_id, c_secret))
        if res.status_code == 200:
            dados = res.json()
            gerenciar_token(novo_token=dados.get("refresh_token"))
            st.session_state.access_token = dados.get("access_token")
            return True
        return False
    except:
        return False

def buscar_dados_ca(endpoint, d_inicio, d_fim):
    if 'access_token' not in st.session_state:
        if not renovar_acesso_ca(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {
        "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
        "data_vencimento_ate": d_fim.strftime('%Y-%m-%d')
    }
    
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 401:
        if renovar_acesso_ca():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("📊 Painel Financeiro JRM")

with st.sidebar:
    st.header("Configurações")
    data_ini = st.date_input("Vencimento inicial", datetime(2026, 4, 1))
    data_fim = st.date_input("Vencimento final", datetime(2026, 4, 30))
    st.divider()
    btn_sync = st.button("🔄 Sincronizar Agora")

if btn_sync:
    with st.spinner("Conectando e buscando dados..."):
        receber = buscar_dados_ca("contas-a-receber", data_ini, data_fim)
        pagar = buscar_dados_ca("contas-a-pagar", data_ini, data_fim)
        
        if receber or pagar:
            df_r = pd.DataFrame(receber)
            df_p = pd.DataFrame(pagar)
            
            # Ajuste de colunas caso a API retorne nomes diferentes
            v_r = df_r['value'].sum() if not df_r.empty and 'value' in df_r.columns else 0
            v_p = df_p['value'].sum() if not df_p.empty and 'value' in df_p.columns else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("A Receber", f"R$ {v_r:,.2f}")
            col2.metric("A Pagar", f"R$ {v_p:,.2f}")
            col3.metric("Saldo Previsto", f"R$ {v_r - v_p:,.2f}")
            
            st.divider()
            tab1, tab2 = st.tabs(["💰 Receitas", "💸 Despesas"])
            with tab1:
                st.dataframe(df_r, use_container_width=True)
            with tab2:
                st.dataframe(df_p, use_container_width=True)
        else:
            st.info("Nenhum dado financeiro retornado para o período.")
