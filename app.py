import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
import os
import toml
import json
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="Fluxo de Caixa JRM", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        .stAppDeployButton, [data-testid="stDeployButton"],
        [data-testid="stToolbarActionButtonIcon"],
        button[data-testid="stBaseButton-header"],
        [data-testid="stViewerBadge"], footer { display: none !important; }

        .card-container {
            background-color: var(--secondary-background-color); 
            color: var(--text-color);
            padding: 20px;
            border-radius: 12px;
            border-left: 5px solid #34495e;
            box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 10px;
        }
        .card-title { font-size: 13px; opacity: 0.8; margin-bottom: 5px; font-weight: 500; text-transform: uppercase; }
        .card-value { font-size: 24px; font-weight: bold; }
        .border-receber { border-left-color: #2ecc71 !important; }
        .border-pagar { border-left-color: #e74c3c !important; }
        .border-saldo { border-left-color: #3498db !important; }
        .border-banco { border-left-color: #f1c40f !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO ---

@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_json = os.getenv("GOOGLE_CREDS_JSON")
        if not creds_json:
            if "google_sheets" in st.secrets:
                creds_info = st.secrets["google_sheets"].to_dict()
            else:
                st.error("Variável GOOGLE_CREDS_JSON não configurada.")
                return None
        else:
            creds_info = json.loads(creds_json)

        if "private_key" in creds_info:
            creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        url = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
        return client.open_by_url(url).sheet1
    except Exception as e:
        st.error(f"Erro na ligação com Google: {e}")
        return None

def carregar_segredos_conta_azul():
    caminho = "secrets.toml"
    if os.path.exists(caminho):
        return toml.load(caminho)
    return st.secrets

def format_br(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def obter_token(empresa_nome):
    sh_local = get_sheet()
    if not sh_local: return None
    try:
        segredos = carregar_segredos_conta_azul()
        cell = sh_local.find(empresa_nome)
        rt = sh_local.cell(cell.row, 2).value
        ca = segredos["conta_azul"]
        
        auth_b64 = base64.b64encode(f"{ca['client_id']}:{ca['client_secret']}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
        
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): 
                sh_local.update_cell(cell.row, 2, dados['refresh_token'])
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

def buscar_saldos_bancarios(token):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get("https://api-v2.contaazul.com/v1/financeiro/contas-correntes", headers=headers)
        if res.status_code == 200:
            return sum(conta.get('saldo', 0) for conta in res.json() if conta.get('ativa', True))
    except: pass
    return 0

# --- 3. EXECUÇÃO DO APP ---
sh = get_sheet()
if not sh:
    st.stop()

clientes = [r[0] for r in sh.get_all_values()[1:]]

with st.sidebar:
    st.header("Fluxo de Caixa JRM")
    empresa_sel = st.selectbox("Selecione a Empresa", ["Todos os Clientes"] + clientes)
    periodo_sel = st.selectbox("Escolha o intervalo", ["Hoje", "7 dias", "15 dias", "30 dias", "Personalizado"], index=1)
    hoje = datetime.now().date()
    
    if periodo_sel == "Hoje": data_ini, data_fim = hoje, hoje
    elif periodo_sel == "7 dias": data_ini, data_fim = hoje, hoje + timedelta(days=6)
    elif periodo_sel == "15 dias": data_ini, data_fim = hoje, hoje + timedelta(days=14)
    elif periodo_sel == "30 dias": data_ini, data_fim = hoje, hoje + timedelta(days=29)
    else:
        c_ini, c_fim = st.columns(2)
        data_ini = c_ini.date_input("Início", hoje)
        data_fim = c_fim.date_input("Fim", hoje + timedelta(days=7))
    
    st.divider()
    exibir_bancos = st.checkbox("Exibir Saldo Bancário", value=True)
    exibir_receitas = st.checkbox("Exibir Receitas", value=True)
    exibir_despesas = st.checkbox("Exibir Despesas", value=True)
    exibir_saldo_periodo = st.checkbox("Exibir Saldo do Período", value=True)

st.title("Painel Financeiro")

alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []
saldo_bancos_acumulado = 0  # Variável inicializada para evitar NameError

with st.spinner("Sincronizando com Conta Azul..."):
    for emp in alvo:
        tk = obter_token(emp)
        if tk:
            # Soma saldos atuais dos bancos
            saldo_bancos_acumulado += buscar_saldos_bancarios(tk)
            
            # Busca previsões de Pagar/Receber
            params = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
            p_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, params.copy()))
            r_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, params.copy()))

if p_total or r_total or saldo_bancos_acumulado:
    # Processamento de Dados
    df_dates = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
    df_dates['data_str'] = df_dates['data'].dt.strftime('%Y-%m-%d')
    
    val_p = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series(dtype=float)
    val_r = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series(dtype=float)
    
    df_dates['Pagar'] = df_dates['data_str'].map(val_p).fillna(0)
    df_dates['Receber'] = df_dates['data_str'].map(val_r).fillna(0)
    df_dates['Saldo_Dia'] = df_dates['Receber'] - df_dates['Pagar']
    
    # Exibição dos Cards
    c1, c2, c3, c4 = st.columns(4)
    
    total_receber = df_dates['Receber'].sum()
    total_pagar = df_dates['Pagar'].sum()
    saldo_periodo = total_receber - total_pagar

    if exibir_bancos:
        c1.markdown(f'<div class="card-container border-banco"><div class="card-title">Disponível em Conta</div><div class="card-value" style="color:#f1c40f">{format_br(saldo_bancos_acumulado)}</div></div>', unsafe_allow_html=True)
    if exibir_receitas:
        c2.markdown(f'<div class="card-container border-receber"><div class="card-title">A Receber no Período</div><div class="card-value" style="color:#2ecc71">{format_br(total_receber)}</div></div>', unsafe_allow_html=True)
    if exibir_despesas:
        c3.markdown(f'<div class="card-container border-pagar"><div class="card-title">A Pagar no Período</div><div class="card-value" style="color:#e74c3c">{format_br(-total_pagar)}</div></div>', unsafe_allow_html=True)
    if exibir_saldo_periodo:
        color = "#2ecc71" if saldo_periodo >= 0 else "#e74c3c"
        c4.markdown(f'<div class="card-container border-saldo"><div class="card-title">Resultado do Período</div><div class="card-value" style="color:{color}">{format_br(saldo_periodo)}</div></div>', unsafe_allow_html=True)

    # Card de Saldo Projetado (Destaque)
    st.divider()
    saldo_projetado = saldo_bancos_acumulado + saldo_periodo
    proj_color = "#2ecc71" if saldo_projetado >= 0 else "#e74c3c"
    st.markdown(f"""
        <div style="text-align: center; padding: 20px; border-radius: 12px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1)">
            <h4 style="margin:0; opacity:0.7">SALDO PROJETADO AO FIM DO PERÍODO</h4>
            <h1 style="margin:0; color:{proj_color}">{format_br(saldo_projetado)}</h1>
            <small>Cálculo: Disponível Atual + (Receitas - Despesas do período)</small>
        </div>
    """, unsafe_allow_html=True)

    # Gráfico
    fig = go.Figure()
    if exibir_receitas:
        fig.add_trace(go.Bar(x=df_dates['data'], y=df_dates['Receber'], name='Receitas', marker_color='#2ecc71'))
    if exibir_despesas:
        fig.add_trace(go.Bar(x=df_dates['data'], y=df_dates['Pagar'], name='Despesas', marker_color='#e74c3c'))
    if exibir_saldo_periodo:
        fig.add_trace(go.Scatter(x=df_dates['data'], y=df_dates['Saldo_Dia'], name='Saldo Diário', line=dict(color='#3498db', width=3), mode='lines+markers'))

    diff = (data_fim - data_ini).days
    dtick = 86400000.0 if diff <= 15 else None

    fig.update_layout(
        hovermode="x unified",
        xaxis=dict(tickformat='%d/%m', dtick=dtick, tickmode='linear' if dtick else 'auto'),
        margin=dict(l=10, r=10, t=10, b=50),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.info("Nenhum dado encontrado para as empresas e período selecionados.")
