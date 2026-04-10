import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="Dashboard BPO - Conta Azul", layout="wide")

# Credenciais vindas do st.secrets
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"

# Preparação do Header de Autenticação (Base64)
auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

# --- 2. FUNÇÕES DE BANCO DE DADOS (GOOGLE SHEETS) ---
@st.cache_resource
def init_gspread():
    """Inicializa a conexão com o Google Sheets"""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["google_sheets"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    return client.open_by_url(PLANILHA_URL).sheet1

sheet = init_gspread()

def get_tokens_db():
    """Lê os tokens salvos na planilha"""
    records = sheet.get_all_records()
    return pd.DataFrame(records)

def update_refresh_token_in_sheet(empresa, novo_refresh_token):
    """Atualiza o refresh token na planilha (obrigatório a cada uso)"""
    df = get_tokens_db()
    empresa = empresa.upper().strip()
    try:
        # Localiza a linha da empresa
        row_index = df.index[df['empresa'].str.upper() == empresa].tolist()[0] + 2 
        sheet.update_cell(row_index, 2, novo_refresh_token) 
    except IndexError:
        # Se a empresa não existir na lista, adiciona uma nova linha
        sheet.append_row([empresa, novo_refresh_token])

# --- 3. FUNÇÕES DA API CONTA AZUL ---
def exchange_code_for_token(code):
    """Troca o código da URL pelos primeiros tokens"""
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

def refresh_access_token(empresa, refresh_token_atual):
    """Gera um novo access_token usando o refresh_token salvo"""
    url = "https://auth.contaazul.com/oauth2/token"
    headers = {
        "Authorization": f"Basic {B64_AUTH}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_atual
    }
    response = requests.post(url, headers=headers, data=data)
    
    if response.status_code == 200:
        dados = response.json()
        # Salva o NOVO refresh token que a API enviou (o antigo expira)
        update_refresh_token_in_sheet(empresa, dados.get("refresh_token"))
        return dados.get("access_token")
    else:
        st.error(f"Erro na renovação: {response.text}")
        return None

# --- 4. INTERFACE DO USUÁRIO (STREAMLIT) ---
st.title("📊 Dashboard Consolidado Conta Azul")

# Verificação de Retorno da Autorização (OAuth Code na URL)
query_params = st.query_params
if "code" in query_params:
    code = query_params["code"]
    st.success("✅ Autorização recebida!")
    nome_empresa = st.text_input("Para qual empresa é esta autorização? (Ex: JRM, LGP)")
    if st.button("Confirmar Vinculação"):
        res = exchange_code_for_token(code)
        if "refresh_token" in res:
            update_refresh_token_in_sheet(nome_empresa, res["refresh_token"])
            st.success(f"Empresa {nome_empresa} conectada com sucesso!")
            st.query_params.clear()
            st.rerun()
        else:
            st.error("Erro ao obter tokens. Verifique as credenciais.")

st.divider()

# Sidebar para Seleção de Empresa
df_db = get_tokens_db()
if not df_db.empty:
    lista_empresas = df_db['empresa'].unique().tolist()
    st.sidebar.header("Configurações")
    empresa_selecionada = st.sidebar.selectbox("Selecione a Empresa:", ["Adicionar Nova..."] + lista_empresas)
else:
    empresa_selecionada = "Adicionar Nova..."

if empresa_selecionada == "Adicionar Nova...":
    st.info("Clique no botão abaixo para conectar uma nova conta da Conta Azul ao dashboard.")
    url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state=ESTADO&scope=openid+profile+aws.cognito.signin.user.admin"
    st.link_button("🔗 Conectar Nova Empresa", url_auth)

else:
    # --- LOGICA PRINCIPAL DO DASHBOARD PARA UMA EMPRESA ---
    st.header(f"🏢 Empresa: {empresa_selecionada}")
    
    # Busca o refresh token na planilha
    refresh_token_db = df_db.loc[df_db['empresa'] == empresa_selecionada, 'refresh_token'].values[0]
    
    if st.button("🔄 Sincronizar Dados Financeiros", type="primary"):
        with st.spinner("Atualizando tokens e buscando saldos..."):
            # 1. Renova o acesso
            token_acesso = refresh_access_token(empresa_selecionada, refresh_token_db)
            
            if token_acesso:
                # 2. Busca contas financeiras
                url_contas = "https://api-v2.contaazul.com/v1/conta-financeira"
                headers_api = {"Authorization": f"Bearer {token_acesso}"}
                res_contas = requests.get(url_contas, headers=headers_api).json()
                
                if "itens" in res_contas:
                    contas = res_contas["itens"]
                    dados_consolidados = []
                    
                    progress_text = st.empty()
                    
                    # 3. Busca saldo individual de cada conta
                    for i, conta in enumerate(contas):
                        progress_text.text(f"Lendo saldo: {conta['nome']} ({i+1}/{len(contas)})")
                        id_c = conta['id']
                        url_s = f"https://api-v2.contaazul.com/v1/conta-financeira/{id_c}/saldo-atual"
                        res_s = requests.get(url_s, headers=headers_api).json()
                        
                        conta['saldo'] = res_s.get('valor', 0.0)
                        dados_consolidados.append(conta)
                    
                    progress_text.empty()
                    
                    # 4. Exibição
                    df_final = pd.DataFrame(dados_consolidados)
                    
                    # Filtros de visualização
                    df_ativa = df_final[df_final['ativo'] == True].copy()
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Saldo Total (Contas Ativas)", f"R$ {df_ativa['saldo'].sum():,.2f}")
                    with col2:
                        st.metric("Total de Contas", len(df_ativa))
                    
                    st.subheader("Detalhamento por Conta")
                    st.dataframe(
                        df_ativa[['nome', 'banco', 'tipo', 'saldo']], 
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.error("Erro ao processar lista de contas.")
                    st.write(res_contas)
