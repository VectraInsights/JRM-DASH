import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
import os
import toml
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
        .card-title { font-size: 14px; opacity: 0.7; margin-bottom: 5px; font-weight: 500; }
        .card-value { font-size: 26px; font-weight: bold; }
        .border-receber { border-left-color: #2ecc71 !important; }
        .border-pagar { border-left-color: #e74c3c !important; }
        .border-saldo { border-left-color: #3498db !important; }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO ---
def carregar_segredos():
    # 1. Tenta ler o arquivo na raiz (onde o Render o coloca)
    caminho_raiz = "secrets.toml"
    if os.path.exists(caminho_raiz):
        return toml.load(caminho_raiz)
    
    # 2. Se não existir, tenta o padrão do Streamlit
    try:
        return st.secrets.to_dict()
    except:
        return {}

@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        # 1. Carrega o segredo do Render ou do Streamlit
        if os.path.exists("secrets.toml"):
            config = toml.load("secrets.toml")
            creds_info = config["google_sheets"]
        else:
            creds_info = st.secrets["google_sheets"].to_dict()

        st.write(f"Tamanho da chave recebida: {len(creds_info.get('private_key', ''))}")
        st.write(f"Início da chave: {creds_info.get('private_key', '')[:30]}")

        # 2. LIMPEZA AGRESSIVA: Resolve o erro de 29 caracteres
        raw_key = str(creds_info.get("private_key", ""))
        
        # Remove cabeçalhos e limpa TUDO que não for o código Base64
        clean_key = raw_key.replace("-----BEGIN PRIVATE KEY-----", "")
        clean_key = clean_key.replace("-----END PRIVATE KEY-----", "")
        # Remove quebras de linha literais, reais e espaços
        clean_key = clean_key.replace("\\n", "").replace("\n", "").replace(" ", "").strip()
        
        # Reconstrói no formato exato que a API do Google exige
        creds_info["private_key"] = f"-----BEGIN PRIVATE KEY-----\n{clean_key}\n-----END PRIVATE KEY-----\n"

        # 3. Autorização
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        
        url = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
        return client.open_by_url(url).sheet1
        
    except Exception as e:
        st.error(f"Erro na ligação com Google: {e}")
        return None

def format_br(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        segredos = carregar_segredos()
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        ca = segredos["conta_azul"]
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

# --- 3. INTERFACE ---
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
            api_p = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
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

    c1, c2, c3 = st.columns(3)
    if exibir_receitas:
        c1.markdown(f'<div class="card-container border-receber"><div class="card-title">RECEBER</div><div class="card-value" style="color:#2ecc71">{format_br(df_plot["Receber"].sum())}</div></div>', unsafe_allow_html=True)
    if exibir_despesas:
        c2.markdown(f'<div class="card-container border-pagar"><div class="card-title">PAGAR</div><div class="card-value" style="color:#e74c3c">{format_br(-df_plot["Pagar"].sum())}</div></div>', unsafe_allow_html=True)
    if exibir_saldo:
        st_total = df_plot['Saldo'].sum()
        c3.markdown(f'<div class="card-container border-saldo"><div class="card-title">SALDO</div><div class="card-value" style="color:{"#2ecc71" if st_total >=0 else "#e74c3c"}">{format_br(st_total)}</div></div>', unsafe_allow_html=True)

    # --- GRÁFICO (DENTRO DO IF) ---
    fig = go.Figure()
    if exibir_receitas:
        fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
    if exibir_despesas:
        fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
    if exibir_saldo:
        fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo', line=dict(color='#3498db', width=3), mode='lines+markers'))

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
    st.info("Nenhum dado encontrado para o período.")
