import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIG PAGE ---
st.set_page_config(
    page_title="Fluxo de Caixa JRM",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- CSS PROFISSIONAL ---
st.markdown("""
<style>
/* Fundo geral */
.stApp {
    background-color: #0f172a;
    color: #e5e7eb;
}

/* Sidebar */
section[data-testid="stSidebar"] {
    background-color: #111827;
}

/* Remover coisas do Streamlit */
.stAppDeployButton, 
[data-testid="stDeployButton"],
[data-testid="stToolbarActionButtonIcon"],
button[data-testid="stBaseButton-header"],
[data-testid="stViewerBadge"],
footer {
    display: none !important;
}

/* Cards */
.card {
    background: #111827;
    padding: 20px;
    border-radius: 12px;
}

/* Métricas */
.metric-title {
    font-size: 13px;
    opacity: 0.7;
}

.metric-value {
    font-size: 28px;
    font-weight: bold;
}

/* Saldo destaque */
.saldo-card {
    background: linear-gradient(135deg, #1e293b, #0f172a);
    padding: 25px;
    border-radius: 14px;
    text-align: center;
}

/* Título */
.title {
    font-size: 32px;
    font-weight: 600;
}

/* Espaçamento */
.block {
    margin-bottom: 20px;
}
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = st.secrets["google_sheets"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        return client.open_by_url(
            "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
        ).sheet1
    except Exception as e:
        st.error(f"Erro: {e}")
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

        auth_b64 = base64.b64encode(
            f"{ca['client_id']}:{ca['client_secret']}".encode()
        ).decode()

        res = requests.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": rt
            }
        )

        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'):
                sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
    except:
        pass

    return None

def buscar_v2(endpoint, token, params):
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}

    params.update({
        "status": "EM_ABERTO",
        "tamanho_pagina": 100,
        "pagina": 1
    })

    while True:
        res = requests.get(
            f"https://api-v2.contaazul.com{endpoint}",
            headers=headers,
            params=params
        )

        if res.status_code != 200:
            break

        itens = res.json().get('itens', [])
        if not itens:
            break

        for i in itens:
            saldo = i.get('total', 0) - i.get('pago', 0)
            if saldo > 0:
                itens_acumulados.append({
                    "Vencimento": i.get("data_vencimento"),
                    "Valor": saldo
                })

        if len(itens) < 100:
            break

        params["pagina"] += 1

    return itens_acumulados

# --- SIDEBAR ---
sh = get_sheet()
clientes = [r[0] for r in sh.get_all_values()[1:]] if sh else []

with st.sidebar:
    st.header("⚙️ Configurações")

    empresa_sel = st.selectbox(
        "Empresa",
        ["Todos os Clientes"] + clientes
    )

    hoje = datetime.now().date()

    periodo = st.selectbox("Período", [
        "Hoje", "7 dias", "15 dias", "30 dias", "Personalizado"
    ])

    if periodo == "Hoje":
        data_ini = hoje
        data_fim = hoje
    elif periodo == "7 dias":
        data_ini = hoje
        data_fim = hoje + timedelta(days=7)
    elif periodo == "15 dias":
        data_ini = hoje
        data_fim = hoje + timedelta(days=15)
    elif periodo == "30 dias":
        data_ini = hoje
        data_fim = hoje + timedelta(days=30)
    else:
        data_ini = st.date_input("Início", hoje)
        data_fim = st.date_input("Fim", hoje + timedelta(days=7))

    st.divider()

    exibir_receitas = st.checkbox("Receitas", True)
    exibir_despesas = st.checkbox("Despesas", True)
    exibir_saldo = st.checkbox("Saldo", True)

# --- HEADER ---
st.markdown('<div class="title">💰 Fluxo de Caixa</div>', unsafe_allow_html=True)

# --- DADOS ---
alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []

with st.spinner("Carregando dados..."):
    for emp in alvo:
        tk = obter_token(emp)
        if tk:
            params = {
                "data_vencimento_de": data_ini.isoformat(),
                "data_vencimento_ate": data_fim.isoformat()
            }

            p_total.extend(buscar_v2(
                "/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar",
                tk, params.copy()
            ))

            r_total.extend(buscar_v2(
                "/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",
                tk, params.copy()
            ))

# --- PROCESSAMENTO ---
if p_total or r_total:

    df = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
    df['data_str'] = df['data'].dt.strftime('%Y-%m-%d')

    val_p = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series(dtype=float)
    val_r = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series(dtype=float)

    df['Pagar'] = df['data_str'].map(val_p).fillna(0)
    df['Receber'] = df['data_str'].map(val_r).fillna(0)
    df['Saldo'] = df['Receber'] - df['Pagar']
    df['Saldo Acumulado'] = df['Saldo'].cumsum()

    total_r = df['Receber'].sum()
    total_p = df['Pagar'].sum()
    saldo_total = df['Saldo'].sum()

    cor_saldo = "#22c55e" if saldo_total >= 0 else "#ef4444"

    # --- CARDS ---
    c1, c2, c3 = st.columns(3)

    with c1:
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Receber</div>
            <div class="metric-value" style="color:#22c55e">
                {format_br(total_r)}
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="card">
            <div class="metric-title">Pagar</div>
            <div class="metric-value" style="color:#ef4444">
                {format_br(total_p)}
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div class="saldo-card">
            <div class="metric-title">Saldo Líquido</div>
            <div style="font-size:36px; font-weight:bold; color:{cor_saldo}">
                {format_br(saldo_total)}
            </div>
        </div>
        """, unsafe_allow_html=True)

    # --- INSIGHTS ---
    st.markdown("<div class='block'></div>", unsafe_allow_html=True)

    if saldo_total < 0:
        st.warning("⚠️ Fluxo negativo no período")
    else:
        st.success("✅ Fluxo positivo no período")

    pior_dia = df.loc[df['Saldo'].idxmin()]
    st.caption(f"Pior dia: {pior_dia['data'].strftime('%d/%m')} ({format_br(pior_dia['Saldo'])})")

    # --- GRÁFICO ---
    fig = go.Figure()

    if exibir_receitas:
        fig.add_bar(
            x=df['data'],
            y=df['Receber'],
            name="Receitas"
        )

    if exibir_despesas:
        fig.add_bar(
            x=df['data'],
            y=df['Pagar'],
            name="Despesas"
        )

    if exibir_saldo:
        fig.add_scatter(
            x=df['data'],
            y=df['Saldo Acumulado'],
            name="Saldo Acumulado",
            mode='lines',
            line=dict(width=4)
        )

    fig.update_layout(
        barmode='group',
        template="plotly_dark",
        hovermode="x unified",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(tickformat='%d/%m'),
        yaxis=dict(tickformat=',.2f'),
        legend=dict(orientation="h", y=-0.2)
    )

    st.plotly_chart(fig, use_container_width=True)

else:
    st.info("Nenhum dado encontrado.")
