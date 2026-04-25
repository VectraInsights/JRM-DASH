import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
import os
import json
import unicodedata
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
        [data-testid="stStatusWidget"], 
        .stSpinner, 
        [data-testid="stNotificationContent"] {
        display: none !important;
        }
        .stApp > header {
        display: none !important;
        }

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
        .border-banco { border-left-color: #9b59b6 !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES COM CACHE (PERFORMANCE) ---

@st.cache_resource
def get_sheet():
    """Cache da conexão com o Google Sheets (Conecta uma vez e reaproveita)"""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_raw = os.environ.get("GOOGLE_SHEETS_JSON") or st.secrets.get("google_sheets")
        creds_dict = json.loads(creds_raw) if isinstance(creds_raw, str) else dict(creds_raw)
        creds_dict["private_key"] = creds_dict["private_key"].strip().replace("\\n", "\n")
        
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        url = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
        return client.open_by_url(url).sheet1
    except Exception as e:
        st.error(f"Erro Planilha: {e}")
        return None

@st.cache_data(ttl=3600) # Cache de 1 hora para a lista de clientes
def listar_clientes():
    sh = get_sheet()
    return [r[0] for r in sh.get_all_values()[1:]] if sh else []

@st.cache_data(ttl=600) # Cache de 10 minutos para os dados da API
def buscar_dados_conta_azul(empresa_nome, data_ini_iso, data_fim_iso):
    """Agrupa as buscas de API em uma função única cacheada"""
    tk = obter_token(empresa_nome)
    if not tk:
        return 0, [], []
    
    saldo_banco = buscar_saldos_bancarios(tk)
    
    api_params = {"data_vencimento_de": data_ini_iso, "data_vencimento_ate": data_fim_iso}
    pagar = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, api_params.copy())
    receber = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, api_params.copy())
    
    return saldo_banco, pagar, receber

# --- 3. FUNÇÕES DE APOIO (MANTIDAS) ---

def format_br(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        cid = os.environ.get("CONTA_AZUL_CLIENT_ID") or st.secrets["conta_azul"]["client_id"]
        cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET") or st.secrets["conta_azul"]["client_secret"]
        auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
    except: pass
    return None

def buscar_v2(endpoint, token, params):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1})
    while True:
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        itens = res.json().get('itens', [])
        if not itens: break
        for i in itens:
            s = i.get('total', 0) - i.get('pago', 0)
            if s > 0: itens_acum.append({"Vencimento": i.get("data_vencimento"), "Valor": s})
        if len(itens) < 100: break
        params["pagina"] += 1
    return itens_acum

def buscar_saldos_bancarios(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    bancos = ["ITAU", "BRADESCO", "SICOOB"]
    rem_acc = lambda t: "".join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    try:
        res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
        if res.status_code == 200:
            for c in res.json().get('itens', []):
                if any(b in rem_acc(c.get('nome', '')).upper() for b in bancos):
                    r_s = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{c.get('id')}/saldo-atual", headers=headers, timeout=5)
                    if r_s.status_code == 200: total += r_s.json().get('saldo_atual', 0)
    except: pass
    return total

# --- 4. INTERFACE ---
clientes = listar_clientes()

with st.sidebar:
    st.header("Filtros")
    empresa_sel = st.selectbox("Empresa", ["Todos os Clientes"] + clientes)
    periodo_sel = st.selectbox("Intervalo", ["Hoje", "7 dias", "15 dias", "30 dias", "Personalizado"], index=1)
    
    hoje = datetime.now().date()
    if periodo_sel == "Hoje": d_ini, d_fim = hoje, hoje
    elif periodo_sel == "7 dias": d_ini, d_fim = hoje, hoje + timedelta(days=6)
    elif periodo_sel == "15 dias": d_ini, d_fim = hoje, hoje + timedelta(days=14)
    elif periodo_sel == "30 dias": d_ini, d_fim = hoje, hoje + timedelta(days=29)
    else:
        d_ini = st.date_input("Início", hoje)
        d_fim = st.date_input("Fim", hoje + timedelta(days=7))
    
    st.divider()
    ex_b = st.checkbox("Saldo Bancário", True)
    ex_r = st.checkbox("Receitas", True)
    ex_p = st.checkbox("Despesas", True)
    ex_s = st.checkbox("Saldo Período", True)

# --- 5. PROCESSAMENTO ---
alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total, saldo_bancos_total = [], [], 0

with st.spinner("Sincronizando..."):
    for emp in alvo:
        sb, pag, rec = buscar_dados_conta_azul(emp, d_ini.isoformat(), d_fim.isoformat())
        saldo_bancos_total += sb
        p_total.extend(pag)
        r_total.extend(rec)

if p_total or r_total or saldo_bancos_total != 0:
    df = pd.DataFrame({'data': pd.date_range(d_ini, d_fim)})
    df['data_str'] = df['data'].dt.strftime('%Y-%m-%d')
    
    vp = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series(dtype=float)
    vr = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series(dtype=float)
    
    df['Pagar'] = df['data_str'].map(vp).fillna(0)
    df['Receber'] = df['data_str'].map(vr).fillna(0)
    df['Var'] = df['Receber'] - df['Pagar']
    df['Acum'] = saldo_bancos_total + df['Var'].cumsum()

    # --- DISPLAYS ---
    cols = st.columns(4)
    if ex_b: cols[0].markdown(f'<div class="card-container border-banco"><div class="card-title">Disponível</div><div class="card-value" style="color:#9b59b6">{format_br(saldo_bancos_total)}</div></div>', 1)
    if ex_r: cols[1].markdown(f'<div class="card-container border-receber"><div class="card-title">Receber</div><div class="card-value" style="color:#2ecc71">{format_br(df["Receber"].sum())}</div></div>', 1)
    if ex_p: cols[2].markdown(f'<div class="card-container border-pagar"><div class="card-title">Pagar</div><div class="card-value" style="color:#e74c3c">{format_br(-df["Pagar"].sum())}</div></div>', 1)
    
    if ex_s:
        sf = df['Acum'].iloc[-1]
        cor = "#2ecc71" if sf >= 0 else "#e74c3c"
        cols[3].markdown(f'<div class="card-container border-saldo"><div class="card-title">Projetado</div><div class="card-value" style="color:{cor}">{format_br(sf)}</div></div>', 1)

    fig = go.Figure()
    if ex_r: fig.add_trace(go.Bar(x=df['data'], y=df['Receber'], name='Receitas', marker_color='#2ecc71'))
    if ex_p: fig.add_trace(go.Bar(x=df['data'], y=-df['Pagar'], name='Despesas', marker_color='#e74c3c'))
    if ex_s: fig.add_trace(go.Scatter(x=df['data'], y=df['Acum'], name='Saldo', line=dict(color='#3498db', width=4, shape='spline')))

    fig.update_layout(barmode='relative', hovermode="x unified", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
else:
    st.info("Sem dados para este filtro.")
