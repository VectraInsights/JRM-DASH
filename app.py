import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES VIA STREAMLIT SECRETS ---
# Puxando os dados da seção [conta_azul] do seu secrets
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]

# Endpoints Oficiais AWS Cognito
AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api.contaazul.com"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# --- 2. INTEGRAÇÃO GOOGLE SHEETS ---

def get_sheet():
    """Conecta à planilha usando a seção [google_sheets] do secrets"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # Converte a seção do secrets em um dicionário compatível com a biblioteca
        google_creds = dict(st.secrets["google_sheets"])
        creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na conexão com Google Sheets: {e}")
        return None

def salvar_refresh_token(empresa, refresh_token):
    sh = get_sheet()
    if not sh: return
    try:
        col_empresas = sh.col_values(1)
        nome_busca = empresa.strip().upper()
        
        idx = -1
        for i, nome in enumerate(col_empresas):
            if nome.strip().upper() == nome_busca:
                idx = i + 1
                break
        
        if idx > 0:
            sh.update_cell(idx, 2, refresh_token)
        else:
            sh.append_row([empresa, refresh_token])
        st.toast(f"✅ Token de {empresa} salvo com sucesso!")
    except Exception as e:
        st.error(f"Erro ao salvar token na planilha: {e}")

# --- 3. LÓGICA DE AUTENTICAÇÃO (OAUTH2 COGNITO) ---

def obter_novo_access_token(empresa_nome):
    """Realiza o Refresh do token com credenciais no Header e no Body"""
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
    except:
        st.error(f"Empresa {empresa_nome} não encontrada.")
        return None

    auth_pass = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth_pass.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    # Adicionando client_id e client_secret no corpo conforme exigência da Conta Azul
    data = {
        "grant_type": "refresh_token",
        "refresh_token": rt_atual,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    
    res = requests.post(TOKEN_URL, headers=headers, data=data)
    
    if res.status_code == 200:
        return res.json()['access_token']
    else:
        st.error(f"Erro no Refresh: {res.text}")
        return None

# --- 4. INTERFACE ---

with st.sidebar:
    st.header("🔗 Conexão")
    url_login = f"{AUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
    st.link_button("🔑 Vincular Nova Empresa", url_login, type="primary", use_container_width=True)
    
    # Callback de retorno do login
    if "code" in st.query_params:
        st.divider()
        nome_empresa = st.text_input("Identificação da Empresa", placeholder="Ex: JRM")
        if st.button("Confirmar Acesso"):
            auth_pass = f"{CLIENT_ID}:{CLIENT_SECRET}"
            auth_b64 = base64.b64encode(auth_pass.encode()).decode()
            
            # Troca do Code por Token (Credenciais no Header e Body)
            res = requests.post(TOKEN_URL, 
                headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": st.query_params["code"],
                    "redirect_uri": REDIRECT_URI,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET
                })
            
            if res.status_code == 200:
                salvar_refresh_token(nome_empresa, res.json()['refresh_token'])
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"Erro na troca do código: {res.text}")

    st.divider()
    # Listagem de clientes
    sh = get_sheet()
    if sh:
        lista_empresas = pd.DataFrame(sh.get_all_records())['empresa'].tolist()
        emp_selecionada = st.selectbox("Selecione o Cliente", lista_empresas)
    else:
        emp_selecionada = None

# --- 5. DASHBOARD PRINCIPAL ---

st.title("Painel de Controle BPO Financeiro")

if emp_selecionada and st.button("🔄 Sincronizar Dados", use_container_width=True):
    token = obter_novo_access_token(emp_selecionada)
    
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        # Buscando Contas a Pagar como exemplo
        res = requests.get(f"{API_BASE_URL}/v1/financeiro/contas-a-pagar", headers=headers)
        
        if res.status_code == 200:
            itens = res.json().get('itens', [])
            if itens:
                df = pd.DataFrame(itens)
                st.metric("Total de Contas a Pagar", f"R$ {df['valor'].sum():,.2f}")
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Nenhum lançamento encontrado.")
        else:
            st.error(f"Erro na API ({res.status_code}): {res.text}")
    else:
        st.error("Falha ao gerar Token. Tente realizar o login novamente pelo botão lateral.")
