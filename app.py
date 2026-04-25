import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
import os
import toml
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

# --- 2. FUNÇÕES DE APOIO ---

@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        # Tenta pegar das variáveis de ambiente (Render) ou do st.secrets (Local)
        creds_raw = os.environ.get("GOOGLE_SHEETS_JSON") or st.secrets.get("google_sheets")
        
        if isinstance(creds_raw, str):
            creds_dict = json.loads(creds_raw)
        else:
            creds_dict = dict(creds_raw)

        key = creds_dict["private_key"].strip()
        if "\\n" in key:
            key = key.replace("\\n", "\n")
        creds_dict["private_key"] = key

        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        url = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
        return client.open_by_url(url).sheet1
    except Exception as e:
        st.error(f"Erro na conexão Planilha: {e}")
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
                itens_acumulados.append({"Vencimento": i.get("data_vencimento"), "Valor": saldo})
        if len(itens) < 100: break
        params["pagina"] += 1
    return itens_acumulados

def buscar_saldos_bancarios(token):
    headers = {"Authorization": f"Bearer {token}"}
    saldo_acumulado = 0
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    
    def remover_acentos(texto):
        return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

    try:
        res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=15)
        if res.status_code == 200:
            itens = res.json().get('itens', [])
            for conta in itens:
                nome_limpo = remover_acentos(conta.get('nome', '')).upper()
                if any(banco in nome_limpo for banco in bancos_permitidos):
                    id_conta = conta.get('id')
                    res_saldo = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{id_conta}/saldo-atual", headers=headers, timeout=10)
                    if res_saldo.status_code == 200:
                        saldo_acumulado += res_saldo.json().get('saldo_atual', 0)
    except: pass
    return saldo_acumulado

# --- 3. INTERFACE ---
sh = get_sheet()
clientes = [r[0] for r in sh.get_all_values()[1:]] if sh else []

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
        c1, c2 = st.columns(2)
        data_ini = c1.date_input("Início", hoje)
        data_fim = c2.date_input("Fim", hoje + timedelta(days=7))
    
    st.divider()
    exibir_bancos = st.checkbox("Exibir Saldo Bancário", value=True)
    exibir_receitas = st.checkbox("Exibir Receitas", value=True)
    exibir_despesas = st.checkbox("Exibir Despesas", value=True)
    exibir_saldo_periodo = st.checkbox("Exibir Saldo Período", value=True)

st.title("Fluxo de Caixa")

alvo = clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]
p_total, r_total = [], []
saldo_bancos_total = 0

with st.spinner("Sincronizando dados..."):
    for emp in alvo:
        tk = obter_token(emp)
        if tk:
            if exibir_bancos:
                saldo_bancos_total += buscar_saldos_bancarios(tk)
            api_p = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
            p_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, api_p.copy()))
            r_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, api_p.copy()))

if p_total or r_total or saldo_bancos_total != 0:
    df_plot = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
    df_plot['data_str'] = df_plot['data'].dt.strftime('%Y-%m-%d')
    
    val_p = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series(dtype=float)
    val_r = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series(dtype=float)
    
    df_plot['Pagar'] = df_plot['data_str'].map(val_p).fillna(0)
    df_plot['Receber'] = df_plot['data_str'].map(val_r).fillna(0)
    df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

    # Cards principais
    cols = st.columns(4)
    
    if exibir_bancos:
        cols[0].markdown(f'<div class="card-container border-banco"><div class="card-title">Disponível em Conta</div><div class="card-value" style="color:#9b59b6">{format_br(saldo_bancos_total)}</div></div>', unsafe_allow_html=True)
    
    if exibir_receitas:
        cols[1].markdown(f'<div class="card-container border-receber"><div class="card-title">A Receber</div><div class="card-value" style="color:#2ecc71">{format_br(df_plot["Receber"].sum())}</div></div>', unsafe_allow_html=True)
    
    if exibir_despesas:
        cols[2].markdown(f'<div class="card-container border-pagar"><div class="card-title">A Pagar</div><div class="card-value" style="color:#e74c3c">{format_br(-df_plot["Pagar"].sum())}</div></div>', unsafe_allow_html=True)
    
    if exibir_saldo_periodo:
        res_per = df_plot['Saldo'].sum()
        cor = "#2ecc71" if res_per >= 0 else "#e74c3c"
        cols[3].markdown(f'<div class="card-container border-saldo"><div class="card-title">Resultado Período</div><div class="card-value" style="color:{cor}">{format_br(res_per)}</div></div>', unsafe_allow_html=True)

    st.write("---")

    # Gráfico
    fig = go.Figure()
    
    if exibir_receitas:
        fig.add_trace(go.Bar(
            x=df_plot['data'], 
            y=df_plot['Receber'], 
            name='Receitas', 
            marker_color='#2ecc71',
            hovertemplate='Receitas: %{y:,.2f}<extra></extra>'
        ))
    
    if exibir_despesas:
        # Valores negativos para ficarem abaixo do zero
        fig.add_trace(go.Bar(
            x=df_plot['data'], 
            y=-df_plot['Pagar'], 
            name='Despesas', 
            marker_color='#e74c3c',
            hovertemplate='Despesas: %{y:,.2f}<extra></extra>'
        ))
    
    if exibir_saldo_periodo:
        fig.add_trace(go.Scatter(
            x=df_plot['data'], 
            y=df_plot['Saldo'], 
            name='Saldo Diário', 
            line=dict(color='#3498db', width=3), 
            mode='lines+markers'
        ))

    fig.update_layout(
        barmode='relative', # Habilita o empilhamento relativo (positivo/negativo)
        hovermode="x unified",
        xaxis=dict(tickformat='%d/%m', showgrid=False),
        yaxis=dict(zeroline=True, zerolinewidth=2, zerolinecolor='white', showgrid=True),
        margin=dict(l=10, r=10, t=10, b=80),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        # Legendas na parte inferior
        legend=dict(orientation="h", y=-0.4, x=0.5, xanchor="center")
    )
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

    diff = (data_fim - data_ini).days
    dtick = 86400000.0 if diff <= 15 else None

else:
    st.info("Nenhum dado encontrado para os filtros selecionados.")
