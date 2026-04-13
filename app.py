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
API_BASE_URL = "https://api-v2.contaazul.com" 
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
AUTH_URL = "https://auth.contaazul.com/login"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. BANCO DE DADOS (GOOGLE SHEETS) ---
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except: return None

def salvar_refresh_token(empresa, refresh_token):
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
            st.toast(f"🔄 Token de '{empresa}' atualizado!")
        else:
            sh.append_row([empresa, refresh_token])
            st.toast(f"✨ Nova empresa '{empresa}' cadastrada!")
    except: pass

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt_atual, "client_id": CA_ID, "client_secret": CA_SECRET})
        
        if res.status_code == 200:
            dados = res.json()
            novo_rt = dados.get('refresh_token')
            if novo_rt and novo_rt != rt_atual:
                salvar_refresh_token(empresa_nome, novo_rt)
            return dados['access_token']
        return None
    except: return None

# --- 3. INTERFACE LATERAL (FILTROS E LOGIN) ---
with st.sidebar:
    st.header("⚙️ Configurações")
    
    # Seção de Login (Vincular Nova Conta)
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Vincular Nova Conta", url_auth, type="primary", use_container_width=True)
    
    # Lógica para capturar o retorno do OAuth
    params_url = st.query_params
    if "code" in params_url:
        st.divider()
        nome_input = st.text_input("Identificação do Novo Cliente", placeholder="Ex: JTL")
        if st.button("Confirmar Vínculo"):
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
    st.subheader("📅 Filtros de Busca")
    data_inicio = st.date_input("Data Inicial", datetime.now())
    data_fim = st.date_input("Data Final", datetime.now() + timedelta(days=7))
    
    st.divider()
    sh = get_sheet()
    emp_selecionada = None
    if sh:
        try:
            dados_pl = sh.get_all_values()
            if len(dados_pl) > 1:
                df_pl = pd.DataFrame(dados_pl[1:], columns=dados_pl[0])
                lista = df_pl.iloc[:, 0].unique().tolist()
                emp_selecionada = st.selectbox("Selecione o Cliente Ativo", lista)
        except: pass

# --- 4. DASHBOARD ---
st.title("Painel Financeiro JRM")

if emp_selecionada:
    # Botão de Sincronização para evitar tela preta inicial
    if st.button(f"🔄 Sincronizar dados de {emp_selecionada}", use_container_width=True):
        token = obter_novo_access_token(emp_selecionada)
        
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            params_api = {
                "data_vencimento_de": data_inicio.strftime('%Y-%m-%d'),
                "data_vencimento_ate": data_fim.strftime('%Y-%m-%d'),
                "tamanho_pagina": 100
            }
            
            url_busca = f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar"
            res = requests.get(url_busca, headers=headers, params=params_api)
            
            if res.status_code == 200:
                dados_api = res.json().get('itens', [])
                if dados_api:
                    df = pd.DataFrame(dados_api)
                    df['data_vencimento'] = pd.to_datetime(df['data_vencimento'])
                    df['total'] = pd.to_numeric(df['total'], errors='coerce')
                    
                    # Gráficos e Métricas
                    df_resumo = df.groupby('data_vencimento')['total'].sum().reset_index()
                    df_resumo['Data'] = df_resumo['data_vencimento'].dt.strftime('%d/%m')
                    
                    col_m1, col_m2 = st.columns([3, 1])
                    with col_m1:
                        st.subheader("Volume de Vencimentos Diários")
                        st.bar_chart(df_resumo.set_index('Data')['total'])
                    with col_m2:
                        st.metric("Total no Período", f"R$ {df['total'].sum():,.2f}")

                    # Tabela Formatada
                    st.divider()
                    df_view = df[['descricao', 'total', 'data_vencimento']].copy()
                    df_view.columns = ['Descrição', 'Valor (R$)', 'Vencimento']
                    df_view['Vencimento'] = df_view['Vencimento'].dt.strftime('%d/%m/%Y')
                    st.dataframe(df_view, use_container_width=True, hide_index=True)
                else:
                    st.info(f"Nenhum lançamento encontrado para {emp_selecionada} neste período.")
            else:
                st.error(f"Erro na API ({res.status_code}): {res.text}")
        else:
            st.error("Erro ao autenticar. Verifique o token na planilha.")
else:
    st.info("Selecione um cliente na barra lateral para começar.")
