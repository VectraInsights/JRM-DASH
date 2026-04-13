import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES (VIA SECRETS) ---
CA_ID = st.secrets["conta_azul"]["client_id"]
CA_SECRET = st.secrets["conta_azul"]["client_secret"]
CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]

# Endpoints Oficiais (Nova API v2)
AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api-v2.contaazul.com"  # CORRIGIDO PARA V2
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. BANCO DE DADOS (GOOGLE SHEETS) ---

def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na conexão com Planilha: {e}")
        return None

def salvar_refresh_token(empresa, refresh_token):
    sh = get_sheet()
    if not sh: return
    try:
        col_empresas = sh.col_values(1)
        idx = -1
        for i, nome in enumerate(col_empresas):
            if nome.strip().upper() == empresa.strip().upper():
                idx = i + 1
                break
        
        if idx > 0:
            sh.update_cell(idx, 2, refresh_token)
            st.toast(f"🔄 Token de {empresa} atualizado!")
        else:
            sh.append_row([empresa, refresh_token])
            st.toast(f"✨ {empresa} vinculada!")
    except Exception as e:
        st.error(f"Erro ao salvar token: {e}")

# --- 3. AUTENTICAÇÃO COM ROTAÇÃO E REDUNDÂNCIA ---

def obter_novo_access_token(empresa_nome):
    """Realiza o Refresh e trata a ROTAÇÃO (Novo RT enviado pela API)"""
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
    except:
        return None

    auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": rt_atual,
        "client_id": CA_ID,
        "client_secret": CA_SECRET
    }
    
    res = requests.post(TOKEN_URL, headers=headers, data=data)
    
    if res.status_code == 200:
        dados = res.json()
        
        # IMPLEMENTAÇÃO DA ROTAÇÃO: Se vier um novo RT, salva na planilha
        novo_rt = dados.get('refresh_token')
        if novo_rt and novo_rt != rt_atual:
            salvar_refresh_token(empresa_nome, novo_rt)
            
        return dados['access_token']
    else:
        st.error(f"Erro na renovação (Refresh): {res.text}")
        return None

# --- 4. INTERFACE ---

with st.sidebar:
    st.header("⚙️ Configurações")
    
    # Gerar state único para proteção CSRF
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
        
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Login Conta Azul", url_auth, type="primary", use_container_width=True)
    
    # Callback do Login
    params = st.query_params
    if "code" in params:
        if params.get("state") != st.session_state.oauth_state:
            st.error("Erro de segurança: State inválido.")
        else:
            st.divider()
            nome_emp = st.text_input("Nome do Cliente", placeholder="Ex: JRM")
            if st.button("Finalizar Registro"):
                auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
                res = requests.post(TOKEN_URL, 
                    headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "authorization_code",
                        "code": params["code"],
                        "redirect_uri": CA_REDIRECT,
                        "client_id": CA_ID,
                        "client_secret": CA_SECRET
                    })
                
                if res.status_code == 200:
                    salvar_refresh_token(nome_emp, res.json()['refresh_token'])
                    st.query_params.clear()
                    st.rerun()

    st.divider()
    sh = get_sheet()
    if sh:
        lista_empresas = pd.DataFrame(sh.get_all_records())['empresa'].tolist()
        emp_ativa = st.selectbox("Selecione o Cliente", lista_empresas)
    else:
        emp_ativa = None

# --- 5. DASHBOARD ---

st.title("Painel BPO Financeiro - JRM")

if emp_ativa and st.button("🔄 Sincronizar Dados Atualizados", use_container_width=True):
    token = obter_novo_access_token(emp_ativa)
    
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Chamada na API-V2
        res = requests.get(f"{API_BASE_URL}/v1/financeiro/contas-a-pagar", headers=headers)
        
        if res.status_code == 200:
            itens = res.json().get('itens', [])
            if itens:
                df = pd.DataFrame(itens)
                st.metric("Total a Pagar", f"R$ {df['valor'].sum():,.2f}")
                st.dataframe(df[['data_vencimento', 'descricao', 'valor']], use_container_width=True)
            else:
                st.info("Nenhum lançamento encontrado para este período.")
        else:
            st.error(f"Erro na API-V2 ({res.status_code})")
            st.json(res.json())
