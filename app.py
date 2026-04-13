import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES ---
CA_ID = st.secrets["conta_azul"]["client_id"]
CA_SECRET = st.secrets["conta_azul"]["client_secret"]
CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]

TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
AUTH_URL = "https://auth.contaazul.com/login"
API_BASE_URL = "https://api-v2.contaazul.com"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. FUNÇÃO DE CONEXÃO ---
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro de conexão com Google: {e}")
        return None

# --- 3. INTERFACE LATERAL (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Configurações")
    
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
        
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Login Conta Azul", url_auth, type="primary", use_container_width=True)
    
    # Processamento do Retorno (Callback)
    params = st.query_params
    if "code" in params:
        st.divider()
        nome_emp = st.text_input("Nome da Empresa", placeholder="Digite o nome aqui")
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
                sh = get_sheet()
                if sh:
                    # Salva garantindo que a coluna 'empresa' exista
                    sh.append_row([nome_emp, res.json()['refresh_token']])
                    st.success("✅ Salvo! Recarregando...")
                    st.query_params.clear()
                    st.rerun()
            else:
                st.error(f"Erro no Token: {res.text}")

    st.divider()
    
    # --- LEITURA SEGURA DA LISTA DE EMPRESAS ---
    sh = get_sheet()
    emp_ativa = None
    
    if sh:
        try:
            # Pegamos todos os valores brutos para limpar espaços
            data = sh.get_all_values()
            if len(data) > 1: # Tem cabeçalho + pelo menos uma linha
                df = pd.DataFrame(data[1:], columns=data[0])
                # Limpa espaços em branco dos nomes das colunas
                df.columns = [c.strip().lower() for c in df.columns]
                
                if 'empresa' in df.columns:
                    lista_empresas = df['empresa'].unique().tolist()
                    emp_ativa = st.selectbox("Selecione o Cliente", lista_empresas)
                else:
                    st.error("Coluna 'empresa' não encontrada. Verifique se a célula A1 é exatamente 'empresa'.")
            else:
                st.info("Planilha vazia. Faça o Login acima primeiro.")
        except Exception as e:
            st.error(f"Erro ao processar planilha: {e}")

# --- 4. DASHBOARD PRINCIPAL ---
st.title("Painel BPO Financeiro - JRM")

if emp_ativa and st.button("🔄 Sincronizar Dados", use_container_width=True):
    # Lógica de Refresh Token
    try:
        sh = get_sheet()
        cell = sh.find(emp_ativa)
        rt_atual = sh.cell(cell.row, 2).value
        
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        res_token = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": rt_atual,
                "client_id": CA_ID,
                "client_secret": CA_SECRET
            })
        
        if res_token.status_code == 200:
            dados = res_token.json()
            token = dados['access_token']
            
            # Rotação de Refresh Token (se houver um novo)
            novo_rt = dados.get('refresh_token')
            if novo_rt and novo_rt != rt_atual:
                sh.update_cell(cell.row, 2, novo_rt)
            
            # Chamada na API v2
            headers = {"Authorization": f"Bearer {token}"}
            res_api = requests.get(f"{API_BASE_URL}/v1/financeiro/contas-a-pagar", headers=headers)
            
            if res_api.status_code == 200:
                df_pagar = pd.DataFrame(res_api.json().get('itens', []))
                if not df_pagar.empty:
                    st.metric("Total a Pagar", f"R$ {df_pagar['valor'].sum():,.2f}")
                    st.dataframe(df_pagar, use_container_width=True)
                else:
                    st.info("Nenhum lançamento pendente.")
            else:
                st.error(f"Erro API v2: {res_api.status_code}")
        else:
            st.error("Falha ao renovar acesso. Tente fazer o login novamente.")
    except Exception as e:
        st.error(f"Erro na sincronização: {e}")
