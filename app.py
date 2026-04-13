import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES OFICIAIS ---
CLIENT_ID = "6s4takgvge1ansrjhsbhhpieor"
CLIENT_SECRET = "1go5jnhckf3l6tatsv7o1t1jf0257fl4a0q6n7to3591g3vjf60l"
REDIRECT_URI = "https://dashboard-conta-azul.streamlit.app/"

AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api.contaazul.com"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# --- 2. BANCO DE DADOS (GOOGLE SHEETS) ---

def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na planilha: {e}")
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
        else:
            sh.append_row([empresa, refresh_token])
        st.toast(f"✅ {empresa} vinculada com sucesso!")
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

# --- 3. LÓGICA DE AUTENTICAÇÃO (AJUSTADA CONFORME SUPORTE) ---

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
    except:
        return None

    auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    
    # REGRAS DA CONTA AZUL: Credenciais no Header E no Body
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": rt_atual,
        "client_id": CLIENT_ID,      # Adicionado conforme orientação
        "client_secret": CLIENT_SECRET # Adicionado conforme orientação
    }
    
    res = requests.post(TOKEN_URL, headers=headers, data=data)
    
    if res.status_code == 200:
        dados = res.json()
        return dados['access_token']
    else:
        st.error(f"Falha no Refresh: {res.text}")
        return None

# --- 4. INTERFACE ---

with st.sidebar:
    st.header("🔗 Conectar Cliente")
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
    st.link_button("🔑 Login Conta Azul", url_auth, type="primary", use_container_width=True)
    
    if "code" in st.query_params:
        st.divider()
        nome_cli = st.text_input("Nome da Empresa", placeholder="Ex: JRM")
        if st.button("Gravar Acesso"):
            auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            
            # REGRAS DA CONTA AZUL: Credenciais no Body para troca do code
            res = requests.post(TOKEN_URL, 
                headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": st.query_params["code"],
                    "redirect_uri": REDIRECT_URI,
                    "client_id": CLIENT_ID,      # Adicionado conforme orientação
                    "client_secret": CLIENT_SECRET # Adicionado conforme orientação
                })
            
            if res.status_code == 200:
                salvar_refresh_token(nome_cli, res.json()['refresh_token'])
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"Erro no Vínculo: {res.text}")

    st.divider()
    sh = get_sheet()
    lista = pd.DataFrame(sh.get_all_records())['empresa'].tolist() if sh else []
    emp_ativa = st.selectbox("Empresa Selecionada", lista)

# --- 5. VISUALIZAÇÃO ---

st.title("BPO Financeiro JRM")

if emp_ativa and st.button("📥 Sincronizar Agora", use_container_width=True):
    token = obter_novo_access_token(emp_ativa)
    
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        # Exemplo: Contas a Receber
        res = requests.get(f"{API_BASE_URL}/v1/financeiro/contas-a-receber", headers=headers)
        
        if res.status_code == 200:
            df = pd.DataFrame(res.json().get('itens', []))
            if not df.empty:
                st.metric("Total a Receber", f"R$ {df['valor'].sum():,.2f}")
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Nenhum dado encontrado.")
        else:
            st.error(f"Erro API: {res.status_code}")
            st.json(res.json())
