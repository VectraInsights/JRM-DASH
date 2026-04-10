import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go
import time

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

# Inicialização de estados
if 'theme' not in st.session_state: st.session_state.theme = 'dark'

# Cores dinâmicas para o CSS
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"
input_fill = "#1e1e1e" if st.session_state.theme == 'dark' else "#ffffff"
border_color = "#444" if st.session_state.theme == 'dark' else "#ccc"

# --- 2. CSS CUSTOMIZADO ---
st.markdown(f"""
    <style>
        header {{visibility: hidden;}}
        #MainMenu, footer {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        
        /* Barra Lateral */
        [data-testid="stSidebar"] {{
            background-color: {side_bg} !important;
            border-right: 1px solid {border_color};
        }}
        
        /* Inputs e Selects */
        .stSelectbox div, .stDateInput div {{
            background-color: {input_fill} !important;
            color: {txt} !important;
        }}

        /* FIX: FUNDO DOS BOTÕES E CHECKBOXES */
        div.stButton > button, div[data-testid="stCheckbox"] {{
            background-color: {input_fill} !important;
            color: {txt} !important;
            border: 1px solid {border_color} !important;
        }}

        /* BOTÃO DE TEMA FLUTUANTE (Canto Superior Direito) */
        .theme-btn-container {{
            position: fixed;
            top: 15px;
            right: 15px;
            z-index: 999999;
        }}
        
        /* Estilo para a tabela e métricas */
        .stMetric {{ background-color: {side_bg}; padding: 15px; border-radius: 10px; border: 1px solid {border_color}; }}
        .debug-container {{ border: 2px solid #ff4b4b; padding: 15px; border-radius: 10px; background: rgba(255,75,75,0.05); }}
    </style>
    """, unsafe_allow_html=True)

# Botão de Tema (Posicionado via CSS flutuante)
st.markdown('<div class="theme-btn-container">', unsafe_allow_html=True)
if st.button("🌓", key="theme_toggle"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- 3. INTEGRAÇÕES ---
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

def update_token_sheet(empresa, rt):
    sh = get_sheet()
    try:
        cell = sh.find(empresa)
        sh.update_cell(cell.row, 2, rt)
    except:
        sh.append_row([empresa, rt])

def get_new_access_token(empresa):
    sh = get_sheet()
    try:
        cell = sh.find(empresa)
        rt_atual = sh.cell(cell.row, 2).value
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
                            headers={"Authorization": f"Basic {B64_AUTH}"}, 
                            data={"grant_type": "refresh_token", "refresh_token": rt_atual})
        if res.status_code == 200:
            data = res.json()
            update_token_sheet(empresa, data.get("refresh_token"))
            return data.get("access_token")
        return None
    except: return None

# --- 4. BARRA LATERAL ---
with st.sidebar:
    st.title("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    except:
        empresas_list = []
        
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas_list)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown('<div style="height: 60vh;"></div>', unsafe_allow_html=True)
    st.divider()
    # Checkbox discreto para Modo ADM
    adm_mode = st.checkbox("", key="adm_check", label_visibility="collapsed")

# --- 5. LÓGICA DE INTERFACE ---
st.title("📊 Fluxo de Caixa BPO")

if adm_mode:
    with st.container(border=True):
        st.subheader("🔑 Área Administrativa")
        pwd = st.text_input("Senha", type="password")
        if pwd == "8429coconoiaKc#":
            st.success("Acesso Liberado")
            st.link_button("🔌 Conectar Nova Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# Captura de código da URL
if "code" in st.query_params:
    st.info("🎯 Finalizando conexão...")
    nome_emp = st.text_input("Nome da Empresa:")
    if st.button("Salvar Empresa"):
        r = requests.post("https://auth.contaazul.com/oauth2/token", 
                          headers={"Authorization": f"Basic {B64_AUTH}"},
                          data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
        if r.status_code == 200:
            update_token_sheet(nome_emp, r.json().get("refresh_token"))
            st.success("Empresa salva!")
            st.query_params.clear()
            st.rerun()

# --- 6. CONSULTA ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    st.markdown('<div class="debug-container">', unsafe_allow_html=True)
    for emp in lista_alvo:
        token = get_new_access_token(emp)
        if token:
            time.sleep(0.5)
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            params = {"data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'), "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')}
            res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if res.status_code == 200:
                for lanc in res.json():
                    data_points.append({
                        'Data': pd.to_datetime(lanc.get('data_vencimento')),
                        'Tipo': 'Recebimentos' if lanc.get('tipo') == 'RECEBER' else 'Pagamentos',
                        'Valor': float(lanc.get('valor', 0))
                    })
    st.markdown('</div>', unsafe_allow_html=True)

    # --- 7. RESULTADOS ---
    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Recebimentos', 'Pagamentos']:
            if col not in df_daily.columns: df_daily[col] = 0.0
        
        df_daily = df_daily.sort_values('Data')
        df_daily['Saldo Diário'] = df_daily['Recebimentos'] - df_daily['Pagamentos']
        df_daily['Acumulado'] = df_daily['Saldo Diário'].cumsum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {df_daily['Recebimentos'].sum():,.2f}")
        c2.metric("Total a Pagar", f"R$ {df_daily['Pagamentos'].sum():,.2f}")
        c3.metric("Saldo Período", f"R$ {df_daily['Saldo Diário'].sum():,.2f}")

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data'], y=df_daily['Recebimentos'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data'], y=-df_daily['Pagamentos'], name='Pagar', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data'], y=df_daily['Acumulado'], name='Acumulado', line=dict(color='#34495e')))
        fig.update_layout(barmode='relative', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Detalhamento")
        df_tab = df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Acumulado']].copy()
        df_tab['Data'] = df_tab['Data'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_tab, use_container_width=True, hide_index=True)
