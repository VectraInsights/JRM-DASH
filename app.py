import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURAÇÕES BÁSICAS ---
st.set_page_config(page_title="Dashboard BPO - Conta Azul", layout="wide")

# Puxando credenciais do Streamlit Secrets
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]

# URL exata da sua planilha
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"

# Codificação Base64 exigida pela Conta Azul
auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

# --- INTEGRAÇÃO GOOGLE SHEETS ---
@st.cache_resource
def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["google_sheets"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_url(PLANILHA_URL).sheet1

sheet = init_gspread()

def get_tokens_db():
    records = sheet.get_all_records()
    return pd.DataFrame(records)

def update_refresh_token_in_sheet(empresa, novo_refresh_token):
    df = get_tokens_db()
    try:
        # Pega o index e soma 2 (gspread começa na linha 1, mais a linha de cabeçalho)
        row_index = df.index[df['empresa'] == empresa].tolist()[0] + 2 
        sheet.update_cell(row_index, 2, novo_refresh_token) 
    except IndexError:
        # Se for uma empresa nova, adiciona no fim da planilha
        sheet.append_row([empresa, novo_refresh_token])

# --- FUNÇÕES DA API CONTA AZUL ---
def exchange_code_for_token(code):
    url = "https://auth.contaazul.com/oauth2/token"
    headers = {
        "Authorization": f"Basic {B64_AUTH}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }
    response = requests.post(url, headers=headers, data=data)
    return response.json()

def refresh_access_token(empresa, refresh_token):
    url = "https://auth.contaazul.com/oauth2/token"
    headers = {
        "Authorization": f"Basic {B64_AUTH}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        tokens = response.json()
        novo_access_token = tokens.get("access_token")
        novo_refresh_token = tokens.get("refresh_token")
        
        update_refresh_token_in_sheet(empresa, novo_refresh_token)
        return novo_access_token
    else:
        st.error(f"Sessão expirada para {empresa}. Solicite reautorização.")
        return None

def obter_saldos_contas(access_token):
    url = "https://api-v2.contaazul.com/v1/conta-financeira"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    return response.json()

# --- INTERFACE DO STREAMLIT ---
st.title("📊 Painel de Conciliação BPO")

# 1. Processamento do Código de Autorização OAuth
query_params = st.query_params
if "code" in query_params:
    st.info("🔄 Capturando autorização da URL...")
    code = query_params["code"]
    
    # Campo para identificar qual cliente acabou de autorizar
    empresa_alvo = st.text_input("Qual o nome desta empresa? (ex: JTL, ROSE, JRM)")
    if st.button("Vincular Nova Empresa"):
        tokens = exchange_code_for_token(code)
        if "refresh_token" in tokens:
            update_refresh_token_in_sheet(empresa_alvo.upper(), tokens["refresh_token"])
            st.success(f"✅ Integração de {empresa_alvo} concluída!")
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Falha ao autenticar. Tente novamente.")
            st.write(tokens)

st.divider()

# 2. Gestão das Empresas e Extração de Dados
df_tokens = get_tokens_db()
empresas_cadastradas = df_tokens['empresa'].tolist() if not df_tokens.empty else []

st.sidebar.header("Empresas Conectadas")
empresa_selecionada = st.sidebar.selectbox("Selecione um cliente:", ["Adicionar Novo Cliente..."] + empresas_cadastradas)

if empresa_selecionada == "Adicionar Novo Cliente...":
    st.write("### Conectar uma nova empresa na Conta Azul")
    state = "SECURE_STATE"
    auth_url = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state={state}&scope=openid+profile+aws.cognito.signin.user.admin"
    
    st.markdown("""
    1. Certifique-se de estar logado na Conta Azul da empresa do cliente.
    2. Clique no botão abaixo para autorizar este aplicativo.
    """)
    st.link_button("🔑 Autorizar Cliente na Conta Azul", auth_url)

elif empresa_selecionada:
    st.write(f"### Dados do Cliente: {empresa_selecionada}")
    
    refresh_token_atual = df_tokens.loc[df_tokens['empresa'] == empresa_selecionada, 'refresh_token'].values[0]
    
    if pd.isna(refresh_token_atual) or refresh_token_atual == "":
        st.warning("Refresh token não encontrado na planilha. Refaça a autorização.")
    else:
        if st.button("Buscar Contas Financeiras", type="primary"):
            with st.spinner("Atualizando token e buscando dados da Conta Azul..."):
                access_token = refresh_access_token(empresa_selecionada, refresh_token_atual)
                
                if access_token:
                    dados = obter_saldos_contas(access_token)
                    
                    if type(dados) == list: # A API da CA geralmente retorna uma lista em caso de sucesso
                        st.success("Dados importados com sucesso!")
                        df_contas = pd.DataFrame(dados)
                        st.dataframe(df_contas)
                    else:
                        st.error("Erro na comunicação com a API da Conta Azul.")
                        st.write(dados)
