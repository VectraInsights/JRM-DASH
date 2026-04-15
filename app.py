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

# CSS para Limpeza e Estilização dos Cards Customizados
st.markdown("""
    <style>
        /* LIMPEZA TOTAL */
        .stAppDeployButton, [data-testid="stDeployButton"],
        [data-testid="stToolbarActionButtonIcon"],
        button[data-testid="stBaseButton-header"],
        [data-testid="appCreatorAvatar"],
        img[class^="_profileImage_"],
        div[class*="_link_"],
        [data-testid="stViewerBadge"],
        [data-testid="stStatusWidget"],
        footer {
            display: none !important;
        }

        /* CABEÇALHO TRANSPARENTE */
        [data-testid="stHeader"] { background: transparent !important; }
        button[data-testid="stSidebarCollapse"] { visibility: visible !important; }

        /* ESTILO DOS CARDS CUSTOMIZADOS */
        .card-container {
            background-color: #1e1e1e;
            padding: 20px;
            border-radius: 10px;
            border-left: 5px solid #333;
            margin-bottom: 10px;
        }
        .card-label {
            color: #888;
            font-size: 14px;
            margin-bottom: 5px;
        }
        .card-value {
            font-size: 24px;
            font-weight: bold;
        }
        .verde { color: #2ecc71 !important; }
        .vermelho { color: #e74c3c !important; }
        .neutro { color: #34495e !important; }
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
    st.header("Gestão Financeira")
    empresa_sel = st.selectbox("Empresa", ["Todos os Clientes"] + clientes)
    with st.form("datas_form"):
        hoje = datetime.now().date()
        data_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
        data_fim = st.date_input("Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
        st.form_submit_button("Atualizar", type="primary")
    
    st.divider()
    exibir_r = st.checkbox("Receitas", value=True)
    exibir_p = st.checkbox("Despesas", value=True)
    exibir_s = st.checkbox("Saldo", value=True)

st.title("Fluxo de Caixa")

# --- 4. DADOS ---
alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []

with st.spinner("Sincronizando..."):
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

    # --- 5. CARDS COM CORES DINÂMICAS ---
    c1, c2, c3 = st.columns(3)
    
    total_r = df_plot['Receber'].sum()
    total_p = df_plot['Pagar'].sum()
    total_s = df_plot['Saldo'].sum()

    if exibir_r:
        c1.markdown(f'<div class="card-container"><div class="card-label">Total a Receber</div><div class="card-value verde">{format_br(total_r)}</div></div>', unsafe_allow_html=True)
    if exibir_p:
        c2.markdown(f'<div class="card-container"><div class="card-label">Total a Pagar</div><div class="card-value vermelho">{format_br(total_p)}</div></div>', unsafe_allow_html=True)
    if exibir_s:
        cor_saldo = "verde" if total_s >= 0 else "vermelho"
        c3.markdown(f'<div class="card-container"><div class="card-label">Saldo Líquido</div><div class="card-value {cor_saldo}">{format_br(total_s)}</div></div>', unsafe_allow_html=True)

    # --- 6. GRÁFICO ---
    fig = go.Figure()
    if exibir_r: fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
    if exibir_p: fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
    if exibir_s: fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo', line=dict(color='#34495e', width=3)))

    fig.update_layout(hovermode="x unified", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=10, r=10, t=10, b=50))
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.info("Nenhum dado para o período.")
