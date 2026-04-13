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

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. BANCO DE DADOS (GOOGLE SHEETS) ---
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except: return None

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
        return res.json().get('access_token') if res.status_code == 200 else None
    except: return None

# --- 3. INTERFACE LATERAL ---
with st.sidebar:
    st.header("⚙️ Filtros")
    
    # Seleção de Datas - Padrão: Hoje até Hoje + 7
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        data_inicio = st.date_input("Início", datetime.now())
    with col_d2:
        data_fim = st.date_input("Fim", datetime.now() + timedelta(days=7))
    
    st.divider()
    sh = get_sheet()
    emp_selecionada = None
    if sh:
        try:
            dados_pl = sh.get_all_values()
            if len(dados_pl) > 1:
                df_pl = pd.DataFrame(dados_pl[1:], columns=dados_pl[0])
                lista = df_pl.iloc[:, 0].unique().tolist()
                emp_selecionada = st.selectbox("Selecione o Cliente", lista)
        except: pass

# --- 4. DASHBOARD ---
st.title("Painel Financeiro JRM")

if emp_selecionada:
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
                
                # Tratamento de Dados
                df['data_vencimento'] = pd.to_datetime(df['data_vencimento'])
                df['total'] = pd.to_numeric(df['total'], errors='coerce')
                
                # --- GRÁFICOS (PRINCIPAL) ---
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.subheader("Tendência de Gastos por Dia")
                    df_chart = df.groupby('data_vencimento')['total'].sum().reset_index()
                    st.line_chart(df_chart.set_index('data_vencimento'))

                with col2:
                    st.metric("Total no Período", f"R$ {df['total'].sum():,.2f}")
                    # Mini gráfico de barras para composição
                    st.bar_chart(df_chart.set_index('data_vencimento'))

                # --- TABELA FORMATADA ---
                st.divider()
                st.subheader("Detalhamento de Contas")
                
                # Filtro de colunas e renomeação
                df_view = df[['descricao', 'total', 'data_vencimento']].copy()
                df_view.columns = ['Descrição', 'Valor (R$)', 'Vencimento']
                
                # Formatação BR: dd/mm/aaaa
                df_view['Vencimento'] = df_view['Vencimento'].dt.strftime('%d/%m/%Y')
                
                st.dataframe(df_view, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum lançamento para o período selecionado.")
        else:
            st.error(f"Erro {res.status_code}: {res.text}")
