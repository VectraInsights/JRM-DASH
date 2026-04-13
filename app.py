import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
import matplotlib.pyplot as plt
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
        linha_index = next((i + 1 for i, v in enumerate(col_empresas) if v.strip().lower() == nome_busca), -1)
        
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
            if dados.get('refresh_token') and dados['refresh_token'] != rt_atual:
                salvar_refresh_token(empresa_nome, dados['refresh_token'])
            return dados['access_token']
        return None
    except: return None

# --- 3. INTERFACE LATERAL ---
with st.sidebar:
    st.header("⚙️ Configurações")
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Vincular Nova Conta", url_auth, type="primary", use_container_width=True)
    
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
    if st.button(f"🔄 Sincronizar dados de {emp_selecionada}", use_container_width=True):
        token = obter_novo_access_token(emp_selecionada)
        
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            params = {
                "data_vencimento_de": data_inicio.strftime('%Y-%m-%d'),
                "data_vencimento_ate": data_fim.strftime('%Y-%m-%d'),
                "tamanho_pagina": 100
            }
            
            # Busca Pagar e Receber
            res_pagar = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", headers=headers, params=params)
            res_receber = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers=headers, params=params)
            
            if res_pagar.status_code == 200 and res_receber.status_code == 200:
                df_p = pd.DataFrame(res_pagar.json().get('itens', []))
                df_r = pd.DataFrame(res_receber.json().get('itens', []))
                
                # Processamento Pagar
                if not df_p.empty:
                    df_p['data'] = pd.to_datetime(df_p['data_vencimento'])
                    df_p['valor'] = pd.to_numeric(df_p['total'])
                    gp_p = df_p.groupby('data')['valor'].sum().reset_index()
                else: gp_p = pd.DataFrame(columns=['data', 'valor'])

                # Processamento Receber
                if not df_r.empty:
                    df_r['data'] = pd.to_datetime(df_r['data_vencimento'])
                    df_r['valor'] = pd.to_numeric(df_r['total'])
                    gp_r = df_r.groupby('data')['valor'].sum().reset_index()
                else: gp_r = pd.DataFrame(columns=['data', 'valor'])

                # Merging para gráfico unificado
                datas = pd.date_range(data_inicio, data_fim)
                df_final = pd.DataFrame({'data': datas})
                df_final = df_final.merge(gp_p, on='data', how='left').rename(columns={'valor': 'Pagar'})
                df_final = df_final.merge(gp_r, on='data', how='left').rename(columns={'valor': 'Receber'})
                df_final = df_final.fillna(0)
                df_final['Data_BR'] = df_final['data'].dt.strftime('%d/%m')

                # --- GRÁFICO MATPLOTLIB (ESTÁTICO) ---
                fig, ax = plt.subplots(figsize=(12, 6))
                plt.style.use('dark_background') # Combina com o tema do app
                
                # Barras
                width = 0.35
                x = range(len(df_final))
                ax.bar([i - width/2 for i in x], df_final['Receber'], width, label='A Receber', color='#2ecc71') # Verde
                ax.bar([i + width/2 for i in x], df_final['Pagar'], width, label='A Pagar', color='#e74c3c') # Vermelho
                
                # Linha de Tendência (Média Móvel do Saldo Diário)
                df_final['Saldo'] = df_final['Receber'] - df_final['Pagar']
                ax.plot(x, df_final['Saldo'], color='#f1c40f', marker='o', label='Tendência (Saldo)', linewidth=2)

                ax.set_xticks(x)
                ax.set_xticklabels(df_final['Data_BR'], rotation=45)
                ax.legend()
                ax.set_title(f"Fluxo de Caixa: {emp_selecionada}", fontsize=14)
                
                st.pyplot(fig) # Renderiza como imagem estática

                # Métricas Rápidas
                c1, c2, c3 = st.columns(3)
                c1.metric("Total a Receber", f"R$ {df_final['Receber'].sum():,.2f}")
                c2.metric("Total a Pagar", f"R$ {df_final['Pagar'].sum():,.2f}")
                c3.metric("Saldo do Período", f"R$ {df_final['Saldo'].sum():,.2f}")
            else:
                st.error("Erro ao buscar dados das APIs de Receber/Pagar.")
