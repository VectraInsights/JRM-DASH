import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- CONFIGURAÇÕES E CREDENCIAIS ---
# Usando os dados que você forneceu e st.secrets para segurança
CLIENT_ID = "6s4takgvge1ansrjhsbhhpieor"
CLIENT_SECRET = "1go5jnhckf3l6tatsv7o1t1jf0257fl4a0q6n7to3591g3vjf60l"
REDIRECT_URI = "https://dashboard-conta-azul.streamlit.app/"

# Endpoints Oficiais (Fluxo AWS Cognito)
AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api.contaazul.com"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# --- FUNÇÕES DE INFRAESTRUTURA (Google Sheets) ---

def get_sheet():
    """Conecta na planilha onde os Refresh Tokens são armazenados"""
    try:
        # Nota: Certifique-se de ter o segredo 'google_sheets' configurado no Streamlit Cloud
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        # Substitua pela URL da sua planilha se necessário
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro ao conectar na planilha: {e}")
        return None

def update_token_storage(empresa, refresh_token):
    """Salva ou atualiza o refresh_token na planilha"""
    sh = get_sheet()
    if not sh: return
    try:
        col_empresas = sh.col_values(1)
        emp_clean = empresa.strip().upper()
        
        idx = -1
        for i, nome in enumerate(col_empresas):
            if nome.strip().upper() == emp_clean:
                idx = i + 1
                break
        
        if idx > 0:
            sh.update_cell(idx, 2, refresh_token)
            st.toast(f"✅ Token de {empresa} atualizado!")
        else:
            sh.append_row([empresa, refresh_token])
            st.toast(f"✨ {empresa} registrada!")
    except Exception as e:
        st.error(f"Erro ao salvar token: {e}")

# --- LÓGICA DE AUTENTICAÇÃO ---

def get_access_token(empresa_nome):
    """Busca o RT na planilha e gera um novo Access Token"""
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
    except:
        return None

    auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    
    res = requests.post(TOKEN_URL, 
        headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": rt_atual})

    if res.status_code == 200:
        dados = res.json()
        # Atualizamos o RT na planilha pois ele pode rotacionar
        update_token_storage(empresa_nome, dados.get('refresh_token', rt_atual))
        return dados['access_token']
    return None

# --- INTERFACE ---

with st.sidebar:
    st.header("🔗 Autenticação")
    # Link gerado conforme o escopo oficial enviado por você
    url_login = f"{AUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
    st.link_button("🔑 Vincular Nova Empresa", url_login, type="primary", use_container_width=True)
    
    # Processamento do Retorno (Callback)
    params = st.query_params
    if "code" in params:
        st.divider()
        nome_empresa = st.text_input("Nome da Empresa para salvar", placeholder="Ex: JTL")
        if st.button("Finalizar Vínculo"):
            auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            res = requests.post(TOKEN_URL, 
                headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": params["code"],
                    "redirect_uri": REDIRECT_URI
                })
            
            if res.status_code == 200:
                update_token_storage(nome_empresa, res.json()['refresh_token'])
                st.success("Vinculado com sucesso!")
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Falha na troca do code.")
                st.json(res.json())

    st.divider()
    st.header("📊 Filtros")
    sh = get_sheet()
    lista = pd.DataFrame(sh.get_all_records())['empresa'].unique().tolist() if sh else []
    emp_selecionada = st.selectbox("Empresa", lista)

# --- DASHBOARD PRINCIPAL ---

st.title("BPO Financeiro - Dashboard")

if st.button("🔄 Sincronizar Dados", use_container_width=True):
    token = get_access_token(emp_selecionada)
    if token:
        # Exemplo de busca de Contas a Pagar
        headers = {"Authorization": f"Bearer {token}"}
        res = requests.get(f"{API_BASE_URL}/v1/financeiro/contas-a-pagar", headers=headers)
        
        if res.status_code == 200:
            dados = res.json().get('itens', [])
            if dados:
                df = pd.DataFrame(dados)
                
                # Interface limpa conforme solicitado
                c1, c2 = st.columns(2)
                valor_total = df['valor'].sum()
                
                c1.metric("Total a Pagar", f"R$ {valor_total:,.2f}")
                st.dataframe(df, use_container_width=True)
            else:
                st.info("Nenhum lançamento encontrado para esta empresa.")
        else:
            st.error(f"Erro na API: {res.status_code}")
    else:
        st.warning("Não foi possível obter um token válido. Tente vincular a empresa novamente.")
