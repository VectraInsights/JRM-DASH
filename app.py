import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import base64

# --- CONFIGURAÇÕES FIXAS ---
# ID da sua planilha "Tokens_ContaAzul"
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8 (etc...)" # O código abaixo usa o ID completo

# --- FUNÇÃO DE CONEXÃO COM GOOGLE (VERSÃO BLINDADA) ---
def conectar_google():
    try:
        # Puxa os dados da seção [google_sheets] do seu Secrets
        google = st.secrets["google_sheets"]
        
        # LIMPEZA ABSOLUTA: Remove espaços, quebras de linha ou caracteres invisíveis
        b64_str = str(google["private_key_base64"]).strip().replace("\n", "").replace("\r", "").replace(" ", "")
        
        # Decodifica a chave privada que está em Base64
        decoded_key = base64.b64decode(b64_str).decode("utf-8")
        
        info = {
            "type": google["type"],
            "project_id": google["project_id"],
            "private_key_id": google["private_key_id"],
            "private_key": decoded_key,
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
        st.error(f"Erro na conexão com Google: {e}")
        return None

# --- GESTÃO DE TOKENS (PLANILHA) ---
def gerenciar_token(novo_token=None):
    client = conectar_google()
    if not client: return None
    
    try:
        # Abre a planilha pelo ID fixo
        sh = client.open_by_key("10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao")
        ws = sh.worksheet("Tokens")
        
        if novo_token:
            ws.update_acell('B2', novo_token)
            return novo_token
        else:
            return ws.acell('B2').value
    except Exception as e:
        st.error(f"Erro ao acessar a aba 'Tokens' na planilha: {e}")
        return None

# --- RENOVAÇÃO CONTA AZUL ---
def renovar_acesso_ca():
    url = "https://api.contaazul.com/oauth2/token"
    refresh_atual = gerenciar_token()
    
    if not refresh_atual:
        st.error("Não foi possível ler o Refresh Token da planilha.")
        return False
        
    c_id = st.secrets["api"]["client_id"]
    c_secret = st.secrets["api"]["client_secret"]
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_atual.strip()
    }

    try:
        res = requests.post(url, data=payload, auth=(c_id, c_secret))
        if res.status_code == 200:
            dados = res.json()
            # Salva o novo refresh token na planilha para a próxima execução
            gerenciar_token(novo_token=dados.get("refresh_token"))
            # Guarda o access_token na sessão para as buscas atuais
            st.session_state.access_token = dados.get("access_token")
            return True
        else:
            st.error(f"Falha na renovação: {res.status_code} - {res.text}")
            return False
    except Exception as e:
        st.error(f"Erro de comunicação com Conta Azul: {e}")
        return False

# --- BUSCA DE DADOS ---
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
    
    if res.status_code == 401: # Token expirou
        if renovar_acesso_ca():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("📊 Painel Financeiro JRM")

with st.sidebar:
    st.header("Filtros")
    data_ini = st.date_input("Vencimento inicial", datetime(2026, 4, 1))
    data_fim = st.date_input("Vencimento final", datetime(2026, 4, 30))
    btn_sync = st.button("🔄 Sincronizar Agora")

if btn_sync:
    with st.spinner("Conectando ao Conta Azul..."):
        receber = buscar_dados_ca("contas-a-receber", data_ini, data_fim)
        pagar = buscar_dados_ca("contas-a-pagar", data_ini, data_fim)

        if receber or pagar:
            df_receber = pd.DataFrame(receber)
            df_pagar = pd.DataFrame(pagar)
            
            # Cálculo de Métricas (ajuste os nomes das colunas conforme sua API)
            val_receber = df_receber['value'].sum() if 'value' in df_receber.columns else 0
            val_pagar = df_pagar['value'].sum() if 'value' in df_pagar.columns else 0
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Total a Receber", f"R$ {val_receber:,.2f}")
            col2.metric("Total a Pagar", f"R$ {val_pagar:,.2f}")
            col3.metric("Saldo Previsto", f"R$ {val_receber - val_pagar:,.2f}")
            
            st.divider()
            
            aba1, aba2 = st.tabs(["📈 Receitas", "📉 Despesas"])
            with aba1:
                st.dataframe(df_receber, use_container_width=True)
            with aba2:
                st.dataframe(df_pagar, use_container_width=True)
        else:
            st.warning("Nenhum dado financeiro encontrado para as datas selecionadas.")
