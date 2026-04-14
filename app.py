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

st.markdown("""
    <style>
        [data-testid="stHeader"], #MainMenu, footer { display: none !important; }
        .main .block-container { padding-top: 0rem !important; }

        /* CSS RADICAL CONTRA LINHAS DE HOVER */
        .hoverlayer line, .spikeline, .axislines, .hl {
            display: none !important;
            stroke-width: 0px !important;
            visibility: hidden !important;
        }
        
        div[data-testid="stMetric"] {
            background: rgba(128, 128, 128, 0.05); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 15px; border-radius: 10px;
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO ---
@st.cache_resource(show_spinner=False)
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = st.secrets["google_sheets"]
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        # Timeout curto para não travar o app se o Google demorar
        client = gspread.authorize(creds)
        return client.open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        return None
        
        # TESTE DE CONEXÃO (Adicione isso para ver o erro real)
with st.expander("Debug de Conexão"):
    try:
        if "google_sheets" not in st.secrets:
            st.error("A seção [google_sheets] não foi encontrada no Secrets.")
        else:
            test_sheet = get_sheet()
            if test_sheet:
                st.success("Conexão com Google Sheets: OK!")
            else:
                st.error("get_sheet() retornou None. Verifique as permissões do e-mail no Google Drive.")
    except Exception as e:
        st.exception(e)

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
            data={"grant_type": "refresh_token", "refresh_token": rt}, timeout=10)
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
        try:
            res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params, timeout=15)
            if res.status_code != 200: break
            itens = res.json().get('itens', [])
            if not itens: break
            for i in itens:
                saldo = i.get('total', 0) - i.get('pago', 0)
                if saldo > 0: itens_acumulados.append({"Vencimento": i.get("data_vencimento"), "Valor": saldo})
            if len(itens) < 100: break
            params["pagina"] += 1
        except: break
    return itens_acumulados

# --- 3. LÓGICA DE CARREGAMENTO (REFORÇADA) ---
sh = get_sheet()
clientes = []
if sh:
    try:
        # Tenta pegar apenas a primeira coluna para ser mais rápido
        clientes = [r for r in sh.col_values(1)[1:] if r]
    except:
        st.warning("Aviso: Falha ao listar empresas. Verifique a planilha.")

# --- 4. INTERFACE ---
with st.sidebar:
    st.header("Configurações")
    empresa_sel = st.selectbox("Empresa", ["Todos os Clientes"] + clientes)
    
    hoje = datetime.now().date()
    with st.form("datas_form"):
        data_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
        data_fim = st.date_input("Fim", hoje + timedelta(days=17), format="DD/MM/YYYY")
        submit = st.form_submit_button("Sincronizar Dados", type="primary")

st.title("Fluxo de Caixa")

alvo = (clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]) if clientes else []
p_total, r_total = [], []

if alvo:
    with st.spinner("Conectando ao Conta Azul..."):
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
    c1.metric("Total a Receber", format_br(df_plot['Receber'].sum()))
    c2.metric("Total a Pagar", format_br(df_plot['Pagar'].sum()))
    c3.metric("Saldo Líquido", format_br(df_plot['Saldo'].sum()))

    # --- 5. GRÁFICO (REFORÇADO) ---
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        x=df_plot['data'], y=df_plot['Receber'], name='Receitas', 
        marker_color='#2ecc71'
    ))
    fig.add_trace(go.Bar(
        x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', 
        marker_color='#e74c3c'
    ))
    fig.add_trace(go.Scatter(
        x=df_plot['data'], y=df_plot['Saldo'], name='Saldo Líquido', 
        line=dict(color='#34495e', width=3), mode='lines+markers'
    ))

    # BLOQUEIO TOTAL DE SPIKELINES NO PYTHON
    fig.update_traces(xaxis='x', showspikes=False)

    fig.update_layout(
        separators=",.",
        hovermode="x unified", # Melhor leitura no mobile
        xaxis=dict(
            showgrid=False, 
            fixedrange=True,
            tickformat='%d/%m',
            showspikes=False # Trava eixo X
        ),
        yaxis=dict(
            showgrid=True, # Grade leve no Y ajuda a ler valores negativos
            gridcolor='rgba(128,128,128,0.1)',
            fixedrange=True,
            tickformat=',.2f',
            showspikes=False # Trava eixo Y
        ),
        legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
        margin=dict(l=10, r=10, t=20, b=10),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        spikedistance=0,
        hoverdistance=10
    )
    
    st.plotly_chart(fig, use_container_width=True, config={
        'displayModeBar': False,
        'showSpikes': False,
        'staticPlot': False, # Permite hover mas bloqueia ferramentas
        'responsive': True
    })
else:
    if not clientes:
        st.error("Erro: Nenhuma empresa encontrada na planilha ou falha na conexão.")
    else:
        st.info("Selecione os filtros e clique em 'Sincronizar Dados'.")
