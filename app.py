import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES E SEGURANÇA ---
try:
    CA_ID = st.secrets["conta_azul"]["client_id"]
    CA_SECRET = st.secrets["conta_azul"]["client_secret"]
    CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]
except:
    st.error("Erro: Verifique as credenciais no secrets.toml.")
    st.stop()

API_BASE_URL = "https://api-v2.contaazul.com" 
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
AUTH_URL = "https://auth.contaazul.com/login"

st.set_page_config(
    page_title="BPO Dashboard JRM", 
    layout="wide",
    initial_sidebar_state="collapsed" 
)

# --- 2. CSS PARA COMPACTAÇÃO ---
st.markdown("""
    <style>
        .block-container {padding-top: 1rem !important; padding-bottom: 0rem !important;}
        h1 {margin-top: -45px; margin-bottom: 10px; font-size: 1.8rem !important;}
        div[data-testid="stMetric"] {
            padding: 15px; 
            background: rgba(128, 128, 128, 0.08); 
            border-radius: 10px;
            border: 1px solid rgba(128, 128, 128, 0.2);
        }
    </style>
""", unsafe_allow_html=True)

# --- 3. FUNÇÕES DE SUPORTE ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except: return None

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt_atual})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'):
                sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
        return None
    except: return None

def buscar_todos_registros(endpoint, headers, params):
    todos_itens = []
    params["tamanho_pagina"] = 100 
    pagina_atual = 1
    while True: 
        params["pagina"] = pagina_atual
        res = requests.get(f"{API_BASE_URL}{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        itens = res.json().get('itens', [])
        if not itens: break
        todos_itens.extend(itens)
        if len(itens) < 100: break 
        pagina_atual += 1
    return todos_itens

# --- 4. LÓGICA DE PERSISTÊNCIA ---
sh = get_sheet()
clientes = [r[0] for r in sh.get_all_values()[1:]] if sh else []

# Define o padrão como o primeiro cliente da lista se nada estiver selecionado
if "empresa_ativa" not in st.session_state:
    st.session_state.empresa_ativa = clientes[0] if clientes else None
    st.session_state.auto_sync = True # Gatilho para carregar no primeiro run
else:
    st.session_state.auto_sync = False

# --- 5. BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ Configurações")
    
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&state={secrets.token_urlsafe(16)}"
    st.link_button("🔑 Login Conta Azul", url_auth, use_container_width=True)
    
    st.divider()
    data_inicio = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    data_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    # Selectbox atualiza o session_state
    emp_selecionada = st.selectbox("Cliente Ativo", clientes, index=clientes.index(st.session_state.empresa_ativa) if st.session_state.empresa_ativa in clientes else 0)
    st.session_state.empresa_ativa = emp_selecionada
    
    btn_sincronizar = st.button("🔄 Sincronizar agora", use_container_width=True, type="primary")

# --- 6. EXECUÇÃO AUTOMÁTICA OU POR BOTÃO ---
st.title("Painel Financeiro JRM")

if st.session_state.empresa_ativa and (btn_sincronizar or st.session_state.auto_sync):
    with st.spinner(f"Sincronizando {st.session_state.empresa_ativa}..."):
        token = obter_novo_access_token(st.session_state.empresa_ativa)
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            p = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
            
            itens_p = buscar_todos_registros("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", headers, p)
            itens_r = buscar_todos_registros("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers, p)
            
            df_plot = pd.DataFrame({'data': pd.date_range(data_inicio, data_fim)})
            df_p = pd.DataFrame(itens_p)
            df_r = pd.DataFrame(itens_r)

            val_p = df_p.groupby('data_vencimento')['total'].sum() if not df_p.empty else pd.Series()
            val_r = df_r.groupby('data_vencimento')['total'].sum() if not df_r.empty else pd.Series()
            
            df_plot['Pagar'] = df_plot['data'].dt.strftime('%Y-%m-%d').map(val_p).fillna(0)
            df_plot['Receber'] = df_plot['data'].dt.strftime('%Y-%m-%d').map(val_r).fillna(0)
            df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

            c1, c2, c3 = st.columns(3)
            c1.metric("A Receber", f"R$ {df_plot['Receber'].sum():,.2f}")
            c2.metric("A Pagar", f"R$ {df_plot['Pagar'].sum():,.2f}")
            c3.metric("Saldo Período", f"R$ {df_plot['Saldo'].sum():,.2f}")

            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
            fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
            fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo', 
                                     line=dict(color='#2C3E50', width=3),
                                     marker=dict(size=10, symbol='circle', line=dict(width=2, color='white'))))

            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5),
                hovermode="x unified", dragmode=False, height=500,
                xaxis=dict(tickformat='%d/%m', showgrid=False),
                yaxis=dict(gridcolor='rgba(128,128,128,0.2)'),
                margin=dict(l=50, r=20, t=20, b=100)
            )
            
            st.plotly_chart(fig, use_container_width=True, theme="streamlit", config={'displayModeBar': False})
            st.session_state.auto_sync = False # Desliga o auto-sync após a primeira carga
        else:
            st.error("Não foi possível carregar os dados automaticamente. Tente sincronizar manualmente.")
elif not st.session_state.empresa_ativa:
    st.info("Selecione uma empresa na barra lateral para começar.")
