import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="Fluxo de Caixa JRM", layout="wide", initial_sidebar_state="collapsed")

def inject_custom_css(cor_saldo):
    st.markdown(f"""
        <style>
            /* LIMPEZA DE INTERFACE */
            .stAppDeployButton, [data-testid="stDeployButton"],
            [data-testid="stToolbarActionButtonIcon"],
            button[data-testid="stBaseButton-header"],
            [data-testid="appCreatorAvatar"],
            footer {{ display: none !important; }}

            /* FORÇAR CORES NOS CARDS (Independente do Tema) */
            /* Coluna 1: Verde */
            [data-testid="column"]:nth-of-type(1) [data-testid="stMetricValue"] {{
                color: #2ecc71 !important;
                -webkit-text-fill-color: #2ecc71 !important;
            }}
            /* Coluna 2: Vermelho */
            [data-testid="column"]:nth-of-type(2) [data-testid="stMetricValue"] {{
                color: #e74c3c !important;
                -webkit-text-fill-color: #e74c3c !important;
            }}
            /* Coluna 3: Dinâmico */
            [data-testid="column"]:nth-of-type(3) [data-testid="stMetricValue"] {{
                color: {cor_saldo} !important;
                -webkit-text-fill-color: {cor_saldo} !important;
            }}
            
            /* Ajuste de contraste para labels */
            [data-testid="stMetricLabel"] {{
                color: #888 !important;
            }}
        </style>
    """, unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = st.secrets["google_sheets"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        return client.open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except: return None

def format_br(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        ca = st.secrets["conta_azul"]
        auth_b64 = base64.b64encode(f"{ca['client_id']}:{ca['client_secret']}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
    except: pass
    return None

def buscar_v2(endpoint, token, params):
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1})
    while True:
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        itens = res.json().get('itens', [])
        if not itens: break
        for i in itens:
            saldo = i.get('total', 0) - i.get('pago', 0)
            if saldo > 0: itens_acumulados.append({"Vencimento": i.get("data_vencimento"), "Valor": saldo})
        if len(itens) < 100: break
        params["pagina"] += 1
    return itens_acumulados

# --- 3. SIDEBAR ---
sh = get_sheet()
clientes = [r[0] for r in sh.get_all_values()[1:]] if sh else []

with st.sidebar:
    st.header("Configurações")
    empresa_sel = st.selectbox("Empresa", ["Todos os Clientes"] + clientes)
    with st.form("datas_form"):
        hoje = datetime.now().date()
        data_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
        data_fim = st.date_input("Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
        st.form_submit_button("Sincronizar", type="primary")

# --- 4. DADOS ---
alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []

with st.spinner("Carregando..."):
    for emp in alvo:
        tk = obter_token(emp)
        if tk:
            api_params = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
            p_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, api_params.copy()))
            r_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, api_params.copy()))

st.title("Fluxo de Caixa")

if p_total or r_total:
    val_p = pd.DataFrame(p_total)['Valor'].sum() if p_total else 0
    val_r = pd.DataFrame(r_total)['Valor'].sum() if r_total else 0
    total_s = val_r - val_p
    
    # Define a cor do saldo ANTES de injetar o CSS
    cor_dinamica_saldo = "#2ecc71" if total_s >= 0 else "#e74c3c"
    inject_custom_css(cor_dinamica_saldo)

    # Exibição dos cards
    c1, c2, c3 = st.columns(3)
    c1.metric("Total a Receber", format_br(val_r))
    c2.metric("Total a Pagar", format_br(val_p))
    c3.metric("Saldo Líquido", format_br(total_s))

    # Gráfico simples para visualização
    fig = go.Figure()
    fig.add_trace(go.Bar(x=['Receber', 'Pagar'], y=[val_r, val_p], marker_color=['#2ecc71', '#e74c3c']))
    fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Sem dados para o período.")
