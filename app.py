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

# CSS original + cores dos metrics
st.markdown("""
    <style>
        .stAppDeployButton, 
        [data-testid="stDeployButton"],
        [data-testid="stToolbarActionButtonIcon"],
        button[data-testid="stBaseButton-header"] {
            display: none !important;
        }

        [data-testid="appCreatorAvatar"],
        div[class*="_link_gzau3_"] {
            opacity: 0 !important;
            width: 0 !important;
            height: 0 !important;
            pointer-events: none !important;
        }

        [data-testid="stViewerBadge"],
        footer {
            display: none !important;
        }

        [data-testid="stHeader"] {
            background: transparent !important;
        }
        
        button[data-testid="stSidebarCollapse"],
        button[kind="header"] {
            visibility: visible !important;
            pointer-events: auto !important;
        }

        .js-plotly-plot .plotly .hoverlayer {
            z-index: 9999 !important;
        }

        /* CORES DOS NÚMEROS DOS CARDS */
        div[data-testid="metric-container"]:nth-of-type(1) [data-testid="stMetricValue"] {
            color: #2ecc71; /* Receber */
        }

        div[data-testid="metric-container"]:nth-of-type(2) [data-testid="stMetricValue"] {
            color: #e74c3c; /* Pagar */
        }

        div[data-testid="metric-container"]:nth-of-type(3) [data-testid="stMetricValue"] {
            color: white; /* será sobrescrito no saldo */
        }

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
    except Exception as e:
        st.error(f"Erro real detectado: {e}")
        return None

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
            if saldo > 0:
                itens_acumulados.append({
                    "Vencimento": i.get("data_vencimento"),
                    "Valor": saldo
                })
        if len(itens) < 100: break
        params["pagina"] += 1
    return itens_acumulados

# --- 3. INTERFACE ---
sh = get_sheet()
clientes = [r[0] for r in sh.get_all_values()[1:]] if sh else []

with st.sidebar:
    st.header("Fluxo de Caixa JRM")
    empresa_sel = st.selectbox("Selecione a Empresa", ["Todos os Clientes"] + clientes)
    
    # --- LOGICA DO CALENDARIO ---
    st.subheader("Período")
    opcoes_periodo = ["Hoje", "7 dias", "15 dias", "30 dias", "Personalizado"]
    periodo_sel = st.selectbox("Escolha o intervalo", opcoes_periodo, index=1) # Padrão 7 dias

    hoje = datetime.now().date()
    
    if periodo_sel == "Hoje":
        data_ini, data_fim = hoje, hoje
    elif periodo_sel == "7 dias":
        data_ini, data_fim = hoje, hoje + timedelta(days=6)
    elif periodo_sel == "15 dias":
        data_ini, data_fim = hoje, hoje + timedelta(days=14)
    elif periodo_sel == "30 dias":
        data_ini, data_fim = hoje, hoje + timedelta(days=29)
    else:
        # Abre os inputs apenas se for "Personalizado"
        col_ini, col_fim = st.columns(2)
        data_ini = col_ini.date_input("Início", hoje, format="DD/MM/YYYY")
        data_fim = col_fim.date_input("Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
    
    st.divider()
    st.subheader("Visualização")
    exibir_receitas = st.checkbox("Exibir Receitas", value=True)
    exibir_despesas = st.checkbox("Exibir Despesas", value=True)
    exibir_saldo = st.checkbox("Exibir Saldo", value=True)

st.title("Fluxo de Caixa")

alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []

with st.spinner("Sincronizando..."):
    for emp in alvo:
        tk = obter_token(emp)
        if tk:
            api_p = {
                "data_vencimento_de": data_ini.isoformat(),
                "data_vencimento_ate": data_fim.isoformat()
            }
            p_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, api_p.copy()))
            r_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, api_p.copy()))

if p_total or r_total:
    df_plot = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
    df_plot['data_str'] = df_plot['data'].dt.strftime('%Y-%m-%d')
    
    val_p = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series(dtype=float)
    val_r = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series(dtype=float)
    
    df_plot['Pagar'] = df_plot['data_str'].map(val_p).fillna(0)
    df_plot['Receber'] = df_plot['data_str'].map(val_r).fillna(0)
    df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

    # CARDS
    c1, c2, c3 = st.columns(3)

    total_receber = df_plot['Receber'].sum()
    total_pagar = df_plot['Pagar'].sum()
    saldo_total = df_plot['Saldo'].sum()

    if exibir_receitas:
        c1.markdown(f"""
        <div>
            <div style="font-size:14px; opacity:0.8;">Total a Receber</div>
            <div style="font-size:28px; font-weight:bold; color:#2ecc71;">
                {format_br(total_receber)}
            </div>
        </div>
        """, unsafe_allow_html=True)

    if exibir_despesas:
        c2.markdown(f"""
        <div>
            <div style="font-size:14px; opacity:0.8;">Total a Pagar</div>
            <div style="font-size:28px; font-weight:bold; color:#e74c3c;">
                {format_br(-total_pagar)}
            </div>
        </div>
        """, unsafe_allow_html=True)

    if exibir_saldo:
        cor_saldo = "#2ecc71" if saldo_total >= 0 else "#e74c3c"

        c3.markdown(f"""
        <div>
            <div style="font-size:14px; opacity:0.8;">Saldo Líquido</div>
            <div style="font-size:28px; font-weight:bold; color:{cor_saldo};">
                {format_br(saldo_total)}
            </div>
        </div>
        """, unsafe_allow_html=True)

    # --- 4. GRÁFICO ---
    fig = go.Figure()
    
    if exibir_receitas:
        fig.add_trace(go.Bar(
            x=df_plot['data'], y=df_plot['Receber'],
            name='Receitas', marker_color='#2ecc71'
        ))
    
    if exibir_despesas:
        fig.add_trace(go.Bar(
            x=df_plot['data'], y=df_plot['Pagar'],
            name='Despesas', marker_color='#e74c3c'
        ))
    
    if exibir_saldo:
        fig.add_trace(go.Scatter(
            x=df_plot['data'], y=df_plot['Saldo'],
            name='Saldo',
            line=dict(color='#34495e', width=3),
            mode='lines+markers'
        ))

    fig.update_layout(
        hovermode="x unified",
        separators=",.",
        xaxis=dict(
            showgrid=False,
            showspikes=False,
            fixedrange=True,
            tickformat='%d/%m',
            tickangle=-45
        ),
        yaxis=dict(
            showgrid=False,
            showspikes=False,
            fixedrange=True,
            tickformat=',.2f'
        ),
        legend=dict(
            orientation="h",
            y=-0.3,
            x=0.5,
            xanchor="center"
        ),
        margin=dict(l=10, r=10, t=10, b=50),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        hoverlabel=dict(
            bgcolor="#2b2b2b",
            font_size=14,
            font_family="Arial"
        )
    )
    
    st.plotly_chart(fig, use_container_width=True, config={
        'displayModeBar': False,
        'showSpikes': False,
        'responsive': True
    })

else:
    st.info("Nenhum dado encontrado.")
