import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES TÉCNICAS (CONTA AZUL + COGNITO) ---
CLIENT_ID = "6s4takgvge1ansrjhsbhhpieor"
CLIENT_SECRET = "1go5jnhckf3l6tatsv7o1t1jf0257fl4a0q6n7to3591g3vjf60l"
REDIRECT_URI = "https://dashboard-conta-azul.streamlit.app/"

# Endpoints Oficiais AWS Cognito enviados por você
AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api.contaazul.com"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# --- 2. INTEGRAÇÃO GOOGLE SHEETS (ARMAZENAMENTO) ---

def get_sheet():
    """Conecta à planilha de Tokens via Secrets do Streamlit"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        # O segredo 'google_sheets' deve conter o JSON da sua Service Account
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro de conexão com Google Sheets: {e}")
        return None

def salvar_refresh_token(empresa, refresh_token):
    """Grava o RT na planilha para uso futuro"""
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
            st.toast(f"✅ Token de {empresa} atualizado!")
        else:
            sh.append_row([empresa, refresh_token])
            st.toast(f"✨ Nova empresa {empresa} cadastrada!")
    except Exception as e:
        st.error(f"Erro ao salvar token: {e}")

# --- 3. LÓGICA DE AUTENTICAÇÃO (BASIC AUTH) ---

def obter_novo_access_token(empresa_nome):
    """Usa o Refresh Token da planilha para gerar um novo Access Token via Basic Auth"""
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_gravado = sh.cell(cell.row, 2).value
    except:
        st.error(f"Empresa '{empresa_nome}' não encontrada na base.")
        return None

    # O Cognito exige ClientID:ClientSecret em Base64 no Header
    auth_pass = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth_pass.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": rt_gravado
    }
    
    res = requests.post(TOKEN_URL, headers=headers, data=data)
    
    if res.status_code == 200:
        dados = res.json()
        # Se a API rotacionar o Refresh Token, salvamos o novo
        novo_rt = dados.get('refresh_token', rt_gravado)
        if novo_rt != rt_gravado:
            salvar_refresh_token(empresa_nome, novo_rt)
        return dados['access_token']
    else:
        st.error(f"Falha no Refresh (401/400). Erro: {res.text}")
        return None

# --- 4. INTERFACE E NAVEGAÇÃO ---

with st.sidebar:
    st.title("⚙️ Painel BPO")
    
    # Link de Login com o Escopo Único Oficial
    login_link = f"{AUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
    st.link_button("🔑 Vincular Cliente (Conta Azul)", login_link, type="primary", use_container_width=True)
    
    # Lógica de Captura do Code (Callback)
    if "code" in st.query_params:
        st.divider()
        st.warning("Novo vínculo detectado!")
        nome_novo = st.text_input("Apelido da Empresa", placeholder="Ex: JRM Transportes")
        if st.button("Confirmar Registro"):
            auth_pass = f"{CLIENT_ID}:{CLIENT_SECRET}"
            auth_b64 = base64.b64encode(auth_pass.encode()).decode()
            
            res = requests.post(TOKEN_URL, 
                headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": st.query_params["code"],
                    "redirect_uri": REDIRECT_URI
                })
            
            if res.status_code == 200:
                salvar_refresh_token(nome_novo, res.json()['refresh_token'])
                st.success("Cliente vinculado!")
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Erro na troca do código de autorização.")

    st.divider()
    # Lista de empresas direto da planilha
    sh = get_sheet()
    empresas_cadastradas = pd.DataFrame(sh.get_all_records())['empresa'].tolist() if sh else []
    empresa_alvo = st.selectbox("Selecionar Cliente", empresas_cadastradas)
    
    st.info("Filtro de Vencimento")
    data_ini = st.date_input("De", datetime.now())
    data_fim = st.date_input("Até", datetime.now() + timedelta(days=30))

# --- 5. EXECUÇÃO DO DASHBOARD ---

st.header(f"📊 Dashboard Financeiro: {empresa_alvo if empresa_alvo else 'Selecione um cliente'}")

if empresa_alvo and st.button("🚀 Sincronizar Dados Atualizados", use_container_width=True):
    token = obter_novo_access_token(empresa_alvo)
    
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        params = {
            "data_vencimento_de": data_ini.strftime('%Y-%m-%d'),
            "data_vencimento_ate": data_fim.strftime('%Y-%m-%d')
        }
        
        # Busca de dados (Exemplo: Contas a Pagar)
        res_pagar = requests.get(f"{API_BASE_URL}/v1/financeiro/contas-a-pagar", headers=headers, params=params)
        
        if res_pagar.status_code == 200:
            itens = res_pagar.json().get('itens', [])
            if itens:
                df = pd.DataFrame(itens)
                total = df['valor'].sum()
                
                # Layout de cards
                c1, c2 = st.columns(2)
                c1.metric("Total no Período", f"R$ {total:,.2f}")
                c2.metric("Qtd. Lançamentos", len(df))
                
                st.divider()
                st.subheader("Lista de Títulos")
                st.dataframe(df[['data_vencimento', 'descricao', 'valor', 'status']], use_container_width=True)
            else:
                st.info("Nenhum lançamento encontrado para este período.")
        else:
            st.error(f"Erro na API ({res_pagar.status_code}): {res_pagar.text}")
    else:
        st.error("Não foi possível autenticar. O Refresh Token pode ter expirado ou as credenciais estão incorretas.")
