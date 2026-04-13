import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES ---
CA_ID = st.secrets["conta_azul"]["client_id"]
CA_SECRET = st.secrets["conta_azul"]["client_secret"]
CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]

# URL BASE CORRIGIDA (Sem /api e sem barra final)
AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api-v2.contaazul.com" 
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
    """Busca empresa e atualiza se existir; caso contrário, cria nova linha."""
    sh = get_sheet()
    if not sh: return
    try:
        col_empresas = sh.col_values(1)
        nome_busca = empresa.strip().lower()
        linha_index = -1
        for i, valor in enumerate(col_empresas):
            if valor.strip().lower() == nome_busca:
                linha_index = i + 1
                break
        
        if linha_index > 0:
            sh.update_cell(linha_index, 2, refresh_token)
            st.toast(f"🔄 Token de '{empresa}' atualizado na planilha!")
        else:
            sh.append_row([empresa, refresh_token])
            st.toast(f"✨ Nova empresa '{empresa}' cadastrada!")
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- 3. LÓGICA DE AUTENTICAÇÃO ---

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": rt_atual,
                "client_id": CA_ID,
                "client_secret": CA_SECRET
            })
        
        if res.status_code == 200:
            dados = res.json()
            novo_rt = dados.get('refresh_token')
            if novo_rt and novo_rt != rt_atual:
                salvar_refresh_token(empresa_nome, novo_rt)
            return dados['access_token']
        return None
    except:
        return None

# --- 4. INTERFACE LATERAL (SIDEBAR) ---

with st.sidebar:
    st.header("⚙️ Configurações")
    
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
        
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Login Conta Azul", url_auth, type="primary", use_container_width=True)
    
    params_url = st.query_params
    if "code" in params_url:
        st.divider()
        nome_input = st.text_input("Nome do Cliente (ex: JTL)", placeholder="Digite aqui")
        if st.button("Finalizar Vínculo"):
            auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
            res = requests.post(TOKEN_URL, 
                headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "authorization_code",
                    "code": params_url["code"],
                    "redirect_uri": CA_REDIRECT,
                    "client_id": CA_ID,
                    "client_secret": CA_SECRET
                })
            
            if res.status_code == 200:
                salvar_refresh_token(nome_input, res.json()['refresh_token'])
                st.query_params.clear()
                st.rerun()

    st.divider()
    sh = get_sheet()
    emp_selecionada = None
    if sh:
        try:
            dados_pl = sh.get_all_values()
            if len(dados_pl) > 1:
                df_pl = pd.DataFrame(dados_pl[1:], columns=dados_pl[0])
                df_pl.columns = [c.strip().lower() for c in df_pl.columns]
                if 'empresa' in df_pl.columns:
                    lista = df_pl['empresa'].unique().tolist()
                    emp_selecionada = st.selectbox("Selecione o Cliente", lista)
        except:
            pass

# --- 5. DASHBOARD ---

st.title("Painel BPO Financeiro - JRM")

if emp_selecionada and st.button("🔄 Sincronizar Dados", use_container_width=True):
    token = obter_novo_access_token(emp_selecionada)
    
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        
        # Filtros de data OBRIGATÓRIOS
        params_api = {
            "data_vencimento_de": (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d'),
            "data_vencimento_ate": (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d'),
            "pagina": 1,
            "tamanho_pagina": 100
        }
        
        # ENDPOINT DE BUSCA DA NOVA API (V2)
        url_busca = f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar"
        
        res = requests.get(url_busca, headers=headers, params=params_api)
        
        if res.status_code == 200:
            dados_api = res.json().get('itens', [])
            if dados_api:
                df_final = pd.DataFrame(dados_api)
                # O campo de valor na API de busca é geralmente 'total'
                col_valor = 'total' if 'total' in df_final.columns else 'valor'
                
                st.metric("Total a Pagar (Período)", f"R$ {df_final[col_valor].sum():,.2f}")
                st.dataframe(df_final, use_container_width=True)
            else:
                st.info("Nenhum lançamento encontrado para os últimos/próximos 30 dias.")
        else:
            st.error(f"Erro {res.status_code}: {res.text}")
    else:
        st.error("Falha na autenticação. Tente o login novamente.")
