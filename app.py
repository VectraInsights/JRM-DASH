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

# CSS focado em remover o cabeçalho do Streamlit e o menu flutuante do gráfico
st.markdown("""
    <style>
        /* Oculta completamente o cabeçalho do Streamlit (Share, GitHub, etc) */
        header[data-testid="stHeader"] {
            visibility: hidden;
            height: 0% !important;
        }
        
        /* Remove o padding do topo que sobra após esconder o header */
        .main .block-container {
            padding-top: 2rem !important;
        }

        /* Estilo dos Cards de Métricas */
        div[data-testid="stMetric"] {
            background: rgba(128, 128, 128, 0.05); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 15px; border-radius: 10px;
        }
        
        /* Remove bordas extras do gráfico */
        .stPlotlyChart {border: none !important;}
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = dict(st.secrets["google_sheets"])
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except: return None

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        cid = st.secrets["conta_azul"]["client_id"]
        sec = st.secrets["conta_azul"]["client_secret"]
        auth_b64 = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
        return None
    except: return None

def buscar_v2(endpoint, token, params):
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"status": "EM_ABERTO", "tamanho_pagina": 100})
    pagina = 1
    while True:
        params["pagina"] = pagina
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        itens = res.json().get('itens', [])
        if not itens: break
        for i in itens:
            saldo = i.get('total', 0) - i.get('pago', 0)
            if saldo > 0: itens_acumulados.append({"Vencimento": i.get("data_vencimento"), "Valor": saldo})
        if len(itens) < 100: break
        pagina += 1
    return itens_acumulados

# --- 3. BARRA LATERAL ---
sh = get_sheet()
clientes = [r[0] for r in sh.get_all_values()[1:]] if sh else []

with st.sidebar:
    st.header("Fluxo de Caixa JRM")
    empresa_sel = st.selectbox("Selecione a Empresa", ["Todos os Clientes"] + clientes)
    
    with st.form("datas_form"):
        hoje = datetime.now().date()
        data_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
        data_fim = st.date_input("Fim", hoje + timedelta(days=17), format="DD/MM/YYYY")
        btn_update_datas = st.form_submit_button("Atualizar Datas", type="primary")

# --- 4. PROCESSAMENTO ---
st.title("Fluxo de Caixa")

alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []

with st.spinner(f"Sincronizando {empresa_sel}..."):
    for emp in alvo:
        tk = obter_token(emp)
        if tk:
            p_api = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
            p_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, p_api))
            r_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, p_api))

if p_total or r_total:
    datas_periodo = pd.date_range(data_ini, data_fim)
    df_plot = pd.DataFrame({'data': datas_periodo, 'data_str': datas_periodo.strftime('%Y-%m-%d')})
    
    val_p = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series()
    val_r = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series()
    
    df_plot['Pagar'] = df_plot['data_str'].map(val_p).fillna(0)
    df_plot['Receber'] = df_plot['data_str'].map(val_r).fillna(0)
    df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

    # Métricas formatadas BR
    c1, c2, c3 = st.columns(3)
    fmt_br = lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    c1.metric("Total a Receber", fmt_br(df_plot['Receber'].sum()))
    c2.metric("Total a Pagar", fmt_br(df_plot['Pagar'].sum()))
    c3.metric("Saldo Líquido", fmt_br(df_plot['Saldo'].sum()))

    # Gráfico sem Spikelines, sem Linhas Brancas e sem ModeBar
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
    fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
    fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo', line=dict(color='#2C3E50', width=3)))

    fig.update_layout(
        hovermode="x",
        separators=",.",
        xaxis=dict(
            type='date',
            tickformat='%d/%m',
            dtick=86400000.0,
            tickangle=-45,
            showgrid=False,
            showline=False,
            zeroline=False,
            showspikes=False,
            range=[data_ini, data_fim] 
        ),
        yaxis=dict(
            tickformat=',.2f', 
            showgrid=False,
            showline=False,
            zeroline=False,
            showspikes=False
        ),
        legend=dict(orientation="h", y=-0.3, x=0.5, xanchor="center"),
        margin=dict(l=20, r=20, t=20, b=80),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    # config={'displayModeBar': False} remove o menu de zoom/câmera do gráfico
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.info("Nenhum dado encontrado para os filtros selecionados.")
