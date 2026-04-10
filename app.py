import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go
import time
import locale

# --- 1. CONFIGURAÇÃO DE IDIOMA E TEMA ---
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except:
    pass

if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

st.set_page_config(page_title="BPO Dashboard", layout="wide")

# Definição de Cores para Injeção CSS
if st.session_state.theme == 'dark':
    BG_COLOR = "#0e1117"
    TEXT_COLOR = "#ffffff"
    SIDE_BG = "#262730"
    INPUT_BG = "#1e1e1e"
    BORDER = "#444"
else:
    BG_COLOR = "#ffffff"
    TEXT_COLOR = "#31333F"
    SIDE_BG = "#f0f2f6"
    INPUT_BG = "#ffffff"
    BORDER = "#ccc"

# --- 2. CSS ULTRA-AGRESSIVO (Dropdown, Calendário e Inputs) ---
st.markdown(f"""
    <style>
        /* Global e Sidebar */
        .stApp, [data-testid="stSidebar"] {{
            background-color: {BG_COLOR} !important;
            color: {TEXT_COLOR} !important;
        }}
        
        /* CORREÇÃO DO DROPDOWN (Caixa que fica branca no print) */
        div[data-baseweb="select"] > div {{
            background-color: {INPUT_BG} !important;
            color: {TEXT_COLOR} !important;
            border: 1px solid {BORDER} !important;
        }}
        
        /* Lista do Dropdown quando aberta */
        div[data-baseweb="popover"] ul {{
            background-color: {INPUT_BG} !important;
            color: {TEXT_COLOR} !important;
        }}
        
        div[data-baseweb="popover"] li {{
            color: {TEXT_COLOR} !important;
        }}
        
        div[data-baseweb="popover"] li:hover {{
            background-color: {BORDER} !important;
        }}

        /* CORREÇÃO DO CALENDÁRIO */
        div[data-baseweb="calendar"] {{
            background-color: {INPUT_BG} !important;
            color: {TEXT_COLOR} !important;
        }}
        div[data-baseweb="calendar"] button {{
            color: {TEXT_COLOR} !important;
        }}

        /* Inputs de Data e Texto */
        div[data-testid="stDateInput"] input, div.stTextInput input {{
            background-color: {INPUT_BG} !important;
            color: {TEXT_COLOR} !important;
        }}

        /* Botão de Tema Flutuante */
        .theme-float {{
            position: fixed;
            top: 15px;
            right: 15px;
            z-index: 99999;
        }}
        
        header {{visibility: hidden;}}
        #MainMenu {{visibility: hidden;}}
    </style>
    """, unsafe_allow_html=True)

# Botão de Tema (Sempre no canto superior direito)
st.markdown('<div class="theme-float">', unsafe_allow_html=True)
if st.button("🌓", key="toggle_theme"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- 3. INTEGRAÇÕES (API & PLANILHA) ---
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
B64_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

@st.cache_resource
def get_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

def get_access_token(empresa_nome):
    sh = get_sheet()
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
                            headers={"Authorization": f"Basic {B64_AUTH}"}, 
                            data={"grant_type": "refresh_token", "refresh_token": rt})
        if res.status_code == 200:
            token_data = res.json()
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
    except:
        return None

# --- 4. BARRA LATERAL (FILTROS) ---
with st.sidebar:
    st.title("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        lista_empresas = df_db['empresa'].unique().tolist()
    except:
        lista_empresas = []
        
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("Início", datetime.now())
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7))
    
    st.markdown("<br><br>"*10, unsafe_allow_html=True)
    st.divider()
    # Checkbox discreto para Modo ADM
    modo_adm = st.checkbox("", label_visibility="collapsed")

# --- 5. INTERFACE PRINCIPAL ---
st.title("📊 Fluxo de Caixa BPO")

if modo_adm:
    st.info("🔐 Área Administrativa")
    pwd = st.text_input("Senha Master", type="password")
    if pwd == "8429coconoiaKc#":
        url_ca = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        st.link_button("🔌 Conectar Nova Empresa (Conta Azul)", url_ca)
        
        # Se houver retorno de código na URL
        if "code" in st.query_params:
            nova_emp = st.text_input("Nome da empresa autorizada:")
            if st.button("Salvar na Planilha"):
                r = requests.post("https://auth.contaazul.com/oauth2/token",
                                  headers={"Authorization": f"Basic {B64_AUTH}"},
                                  data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
                if r.status_code == 200:
                    get_sheet().append_row([nova_emp, r.json()['refresh_token']])
                    st.success("Sucesso! Empresa adicionada.")
                    st.query_params.clear()
                    time.sleep(1)
                    st.rerun()

# --- 6. PROCESSAMENTO E GRÁFICOS ---
if st.button("🚀 Consultar Fluxo", type="primary"):
    all_data = []
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    
    with st.spinner("Buscando dados na Conta Azul..."):
        for emp in alvos:
            tk = get_access_token(emp)
            if tk:
                url = "https://api.contaazul.com/v1/financeiro/lancamentos"
                params = {
                    "data_inicio": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                    "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
                }
                res = requests.get(url, headers={"Authorization": f"Bearer {tk}"}, params=params)
                if res.status_code == 200:
                    for l in res.json():
                        all_data.append({
                            'Data': pd.to_datetime(l['data_vencimento']),
                            'Tipo': 'Receber' if l['tipo'] == 'RECEBER' else 'Pagar',
                            'Valor': float(l['valor'])
                        })

    if all_data:
        df = pd.DataFrame(all_data)
        df_resumo = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        
        for c in ['Receber', 'Pagar']:
            if c not in df_resumo.columns: df_resumo[c] = 0.0
            
        df_resumo['Saldo'] = df_resumo['Receber'] - df_resumo['Pagar']
        df_resumo['Acumulado'] = df_resumo['Saldo'].cumsum()
        
        # Métricas
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Receber", f"R$ {df_resumo['Receber'].sum():,.2f}")
        m2.metric("Total Pagar", f"R$ {df_resumo['Pagar'].sum():,.2f}")
        m3.metric("Saldo Período", f"R$ {df_resumo['Saldo'].sum():,.2f}")
        
        # Gráfico
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=df_resumo['Receber'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=-df_resumo['Pagar'], name='Pagar', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_resumo['Data'], y=df_resumo['Acumulado'], name='Acumulado', line=dict(color='#34495e', width=3)))
        
        fig.update_layout(barmode='relative', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white")
        st.plotly_chart(fig, use_container_width=True)
        
        # Tabela
        st.subheader("Detalhamento Diário")
        df_tab = df_resumo.copy()
        df_tab['Data'] = df_tab['Data'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_tab, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
