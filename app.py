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

# CSS para Limpeza e Forçar Cores nos Metrics (Baseado na posição da coluna)
def inject_custom_css(cor_saldo):
    st.markdown(f"""
        <style>
            /* LIMPEZA TOTAL (Botões de Deploy, Menu, Rodapé) */
            .stAppDeployButton, [data-testid="stDeployButton"],
            [data-testid="stToolbarActionButtonIcon"],
            button[data-testid="stBaseButton-header"],
            [data-testid="appCreatorAvatar"],
            img[class^="_profileImage_"],
            footer {{ display: none !important; }}

            /* CABEÇALHO TRANSPARENTE */
            [data-testid="stHeader"] {{ background: transparent !important; }}
            button[data-testid="stSidebarCollapse"] {{ visibility: visible !important; }}

            /* CORES DOS CARDS (st.metric) POR COLUNA */
            /* Coluna 1: A Receber (Verde) */
            [data-testid="column"]:nth-of-type(1) [data-testid="stMetricValue"] {{
                color: #2ecc71 !important;
            }}
            /* Coluna 2: A Pagar (Vermelho) */
            [data-testid="column"]:nth-of-type(2) [data-testid="stMetricValue"] {{
                color: #e74c3c !important;
            }}
            /* Coluna 3: Saldo Líquido (Dinâmico) */
            [data-testid="column"]:nth-of-type(3) [data-testid="stMetricValue"] {{
                color: {cor_saldo} !important;
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
    st.header("Menu Financeiro")
    empresa_sel = st.selectbox("Selecione a Empresa", ["Todos os Clientes"] + clientes)
    with st.form("datas_form"):
        hoje = datetime.now().date()
        data_ini = st.date_input("Data Início", hoje, format="DD/MM/YYYY")
        data_fim = st.date_input("Data Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
        st.form_submit_button("Sincronizar Dados", type="primary")
    
    st.divider()
    exibir_r = st.checkbox("Ver Receitas", value=True)
    exibir_p = st.checkbox("Ver Despesas", value=True)
    exibir_s = st.checkbox("Ver Saldo", value=True)

st.title("Fluxo de Caixa")

# --- 4. PROCESSAMENTO ---
alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []

with st.spinner("Conectando à Conta Azul..."):
    for emp in alvo:
        tk = obter_token(emp)
        if tk:
            api_params = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
            p_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, api_params.copy()))
            r_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, api_params.copy()))

if p_total or r_total:
    df_plot = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
    df_plot['data_str'] = df_plot['data'].dt.strftime('%Y-%m-%d')
    val_p = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series(dtype=float)
    val_r = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series(dtype=float)
    df_plot['Pagar'] = df_plot['data_str'].map(val_p).fillna(0)
    df_plot['Receber'] = df_plot['data_str'].map(val_r).fillna(0)
    df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

    # --- 5. LÓGICA DE CORES E EXIBIÇÃO ---
    total_saldo = df_plot['Saldo'].sum()
    cor_dinamica_saldo = "#2ecc71" if total_saldo >= 0 else "#e74c3c"
    
    # Injeta o CSS com a cor do saldo calculada
    inject_custom_css(cor_dinamica_saldo)

    cols = st.columns(3)
    if exibir_r: cols[0].metric("Total a Receber", format_br(df_plot['Receber'].sum()))
    if exibir_p: cols[1].metric("Total a Pagar", format_br(df_plot['Pagar'].sum()))
    if exibir_s: cols[2].metric("Saldo Líquido", format_br(total_saldo))

    # --- 6. GRÁFICO INTEGRADO ---
    fig = go.Figure()
    if exibir_r: fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
    if exibir_p: fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
    if exibir_s: fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo Diário', line=dict(color='#34495e', width=3)))

    fig.update_layout(
        hovermode="x unified",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=50),
        legend=dict(orientation="h", y=-0.3, x=0.5, xanchor="center")
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.info("Nenhum lançamento encontrado para o período selecionado.")
