import streamlit as st
import requests
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES FIXAS ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"

# --- CONEXÃO GOOGLE CORRIGIDA ---
def conectar_google():
    try:
        if "google_sheets" not in st.secrets:
            st.error("Seção [google_sheets] não encontrada no Secrets.")
            return None

        google = st.secrets["google_sheets"]

        # ✅ CORREÇÃO DEFINITIVA DO PEM
        private_key = google["private_key"].replace("\\n", "\n")

        info = {
            "type": google["type"],
            "project_id": google["project_id"],
            "private_key_id": google["private_key_id"],
            "private_key": private_key,
            "client_email": google["client_email"],
            "client_id": google["client_id"],
            "auth_uri": google["auth_uri"],
            "token_uri": google["token_uri"],
            "auth_provider_x509_cert_url": google["auth_provider_x509_cert_url"],
            "client_x509_cert_url": google["client_x509_cert_url"],
        }

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = Credentials.from_service_account_info(info, scopes=scopes)
        return gspread.authorize(creds)

    except Exception as e:
        st.error(f"Erro Crítico na Conexão Google: {e}")
        return None


# --- GERENCIAMENTO TOKEN ---
def gerenciar_token(novo_token=None):
    client = conectar_google()
    if not client:
        return None

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


# --- RENOVA TOKEN CONTA AZUL ---
def renovar_acesso_ca():
    refresh_atual = gerenciar_token()
    if not refresh_atual:
        return False

    url = "https://api.contaazul.com/oauth2/token"
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

            gerenciar_token(novo_token=dados.get("refresh_token"))
            st.session_state.access_token = dados.get("access_token")

            return True

        else:
            st.error(f"Erro ao renovar token: {res.text}")
            return False

    except Exception as e:
        st.error(f"Erro na requisição Conta Azul: {e}")
        return False


# --- BUSCA DADOS CONTA AZUL ---
def buscar_dados_ca(endpoint, d_inicio, d_fim):
    if 'access_token' not in st.session_state:
        if not renovar_acesso_ca():
            return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"

    headers = {
        "Authorization": f"Bearer {st.session_state.access_token}"
    }

    params = {
        "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
        "data_vencimento_ate": d_fim.strftime('%Y-%m-%d')
    }

    res = requests.get(url, headers=headers, params=params)

    if res.status_code == 401:
        if renovar_acesso_ca():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)

    if res.status_code == 200:
        return res.json()
    else:
        st.error(f"Erro API Conta Azul: {res.text}")
        return []


# --- INTERFACE ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("📊 Painel Financeiro JRM")

with st.sidebar:
    st.header("Filtros")

    data_ini = st.date_input("Vencimento inicial", datetime(2026, 4, 1))
    data_fim = st.date_input("Vencimento final", datetime(2026, 4, 30))

    sync = st.button("🔄 Sincronizar Agora")


# --- EXECUÇÃO ---
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

            with t1:
                st.dataframe(df_r, use_container_width=True)

            with t2:
                st.dataframe(df_p, use_container_width=True)

        else:
            st.info("Nenhum dado encontrado para o período.")
