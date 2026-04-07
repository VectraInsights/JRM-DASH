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
        
        # 1. LIMPEZA RADICAL DO BASE64
        # Remove TUDO que não for caractere válido de Base64
        b64_raw = str(google["private_key_base64"]).strip()
        b64_clean = re.sub(r'[^a-zA-Z0-9+/=]', '', b64_raw)
        
        # 2. DECODIFICAÇÃO PARA BYTES
        # O erro InvalidByte ocorre na interpretação do PEM, então tratamos o dado bruto
        decoded_bytes = base64.b64decode(b64_clean)
        
        # Converte para string e remove o que não for a chave propriamente dita
        decoded_str = decoded_bytes.decode("utf-8", errors="ignore")
        
        # 3. RECONSTRUÇÃO DO FORMATO PEM (Obrigatório para a biblioteca cryptography)
        # Removemos qualquer header/footer existente e limpamos espaços
        core = decoded_str.replace("-----BEGIN PRIVATE KEY-----", "")
        core = core.replace("-----END PRIVATE KEY-----", "")
        # Remove \n literais, quebras de linha e espaços
        core = core.replace("\\n", "").replace("\n", "").replace("\r", "").strip()
        
        # Monta a chave com quebras de linha a cada 64 caracteres (padrão RFC)
        # Isso evita o erro de "InvalidByte" no carregamento do PEM
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
        # Mostra o erro na tela para sabermos se a chave passou pelo validador
        st.error(f"Erro Crítico na Conexão Google: {e}")
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
        st.error(f"Erro ao acessar aba de Tokens: {e}")
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
    st.header("Filtros")
    data_ini = st.date_input("Vencimento inicial", datetime(2026, 4, 1))
    data_fim = st.date_input("Vencimento final", datetime(2026, 4, 30))
    sync = st.button("🔄 Sincronizar Agora")

if sync:
    with st.spinner("Sincronizando com Conta Azul..."):
        receber = buscar_dados_ca("contas-a-receber", data_ini, data_fim)
        pagar = buscar_dados_ca("contas-a-pagar", data_ini, data_fim)
        
        if receber or pagar:
            df_r = pd.DataFrame(receber)
            df_p = pd.DataFrame(pagar)
            
            v_r = df_r['value'].sum() if not df_r.empty and 'value' in df_r.columns else 0
            v_p = df_p['value'].sum() if not df_p.empty and 'value' in df_p.columns else 0
            
            c1, c2, c3 = st.columns(3)
            c1.metric("A Receber", f"R$ {v_r:,.2f}")
            c2.metric("A Pagar", f"R$ {v_p:,.2f}")
            c3.metric("Saldo Líquido", f"R$ {v_r - v_p:,.2f}")
            
            st.divider()
            t1, t2 = st.tabs(["Contas a Receber", "Contas a Pagar"])
            t1.dataframe(df_r, use_container_width=True)
            t2.dataframe(df_p, use_container_width=True)
        else:
            st.info("Nenhum dado encontrado para o período.")
