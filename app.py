import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURAÇÕES BÁSICAS ---
st.set_page_config(page_title="Dashboard Conta Azul", layout="wide")

CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_NOME = "Tokens_ContaAzul" # Mude para o nome exato do seu arquivo no Google Drive

# Codificação Base64 exigida pela Conta Azul
auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

# --- INTEGRAÇÃO GOOGLE SHEETS ---
@st.cache_resource
def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open(PLANILHA_NOME).sheet1

sheet = init_gspread()

def get_tokens_db():
    """Retorna os dados da planilha como DataFrame"""
    records = sheet.get_all_records()
    return pd.DataFrame(records)

def update_refresh_token_in_sheet(empresa, novo_refresh_token):
    """Localiza a empresa na planilha e atualiza o token correspondente"""
    df = get_tokens_db()
    try:
        # Acha o índice da linha da empresa (gspread usa índice base 1, e a linha 1 é o cabeçalho)
        row_index = df.index[df['empresa'] == empresa].tolist()[0] + 2 
        sheet.update_cell(row_index, 2, novo_refresh_token) # Coluna B (2) é o refresh_token
    except IndexError:
        # Se a empresa não existir, adiciona uma nova linha
        sheet.append_row([empresa, novo_refresh_token])

# --- FUNÇÕES DA API CONTA AZUL ---
def exchange_code_for_token(code):
    """Troca o código de autorização inicial pelos tokens de acesso e refresh"""
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
    """Renova o access_token expirado e salva o NOVO refresh_token na planilha"""
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
        
        # ATENÇÃO: O refresh_token muda a cada renovação. É obrigatório salvar o novo!
        update_refresh_token_in_sheet(empresa, novo_refresh_token)
        return novo_access_token
    else:
        st.error(f"Erro ao renovar token da empresa {empresa}. É necessário reautorizar.")
        return None

def get_contas_financeiras(access_token):
    """Exemplo de requisição: Retorna as contas financeiras por filtro"""
    url = "https://api-v2.contaazul.com/v1/conta-financeira"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    return response.json()

# --- INTERFACE E FLUXO DO STREAMLIT ---
st.title("Dashboard Conciliado - BPO Financeiro")

# 1. Captura de redirecionamento OAuth
query_params = st.query_params
if "code" in query_params:
    st.info("Código de autorização detectado na URL. Processando...")
    code = query_params["code"]
    
    # Seleção de qual empresa este código pertence
    empresa_alvo = st.text_input("Qual empresa você está vinculando agora?")
    if st.button("Vincular Empresa"):
        tokens = exchange_code_for_token(code)
        if "refresh_token" in tokens:
            update_refresh_token_in_sheet(empresa_alvo, tokens["refresh_token"])
            st.success(f"Integração da empresa {empresa_alvo} realizada com sucesso!")
            # Limpa os parâmetros da URL para evitar reprocessamento
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Falha ao obter os tokens.")
            st.json(tokens)

# 2. Gestão das Empresas já cadastradas na Planilha
df_tokens = get_tokens_db()
empresas_cadastradas = df_tokens['empresa'].tolist() if not df_tokens.empty else []

st.sidebar.header("Gestão de Conexões")
empresa_selecionada = st.sidebar.selectbox("Selecione a Empresa", ["Nova Empresa..."] + empresas_cadastradas)

if empresa_selecionada == "Nova Empresa...":
    st.write("### Conectar uma nova empresa")
    state = "ESTADO_GERADO_ALEATORIAMENTE"
    auth_url = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state={state}&scope=openid+profile+aws.cognito.signin.user.admin"
    st.markdown(f"**Passo a passo:**\n1. Logue no Conta Azul com o usuário administrador da empresa cliente.\n2. Clique no link abaixo para autorizar.\n3. Você será redirecionado de volta para cá.")
    st.link_button("Autorizar Conta Azul", auth_url)

elif empresa_selecionada:
    st.write(f"### Dashboard: {empresa_selecionada}")
    
    # Puxa o refresh token atual da planilha para esta empresa
    refresh_token_atual = df_tokens.loc[df_tokens['empresa'] == empresa_selecionada, 'refresh_token'].values[0]
    
    if pd.isna(refresh_token_atual) or refresh_token_atual == "":
        st.warning("Nenhum token encontrado para esta empresa. Por favor, faça a autorização novamente.")
    else:
        if st.button("Carregar Dados Financeiros"):
            with st.spinner("Renovando token e buscando dados..."):
                # Renova o token de acesso (e salva o novo refresh na planilha)
                access_token = refresh_access_token(empresa_selecionada, refresh_token_atual)
                
                if access_token:
                    # Chamada à API da Conta Azul usando o token renovado
                    dados = get_contas_financeiras(access_token)
                    
                    if "Aviso" not in dados: # Checagem básica de erro
                        st.success("Dados obtidos com sucesso!")
                        # Exibição básica; aqui você aplicará suas métricas de conciliação
                        st.json(dados) 
                    else:
                        st.error("Erro ao buscar recursos.")
