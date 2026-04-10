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

if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

# Definição de Cores para o CSS
if st.session_state.theme == 'dark':
    BG_COLOR = "#0e1117"
    TEXT_COLOR = "#ffffff"
    INPUT_BG = "#1e1e1e"
    BORDER = "#444"
else:
    BG_COLOR = "#ffffff"
    TEXT_COLOR = "#31333F"
    INPUT_BG = "#f0f2f6"
    BORDER = "#ccc"

# --- 2. CSS ULTRA-CORRETIVO (FIX DOS BUGS VISUAIS) ---
st.markdown(f"""
    <style>
        header {{visibility: hidden;}}
        .stApp {{ background-color: {BG_COLOR}; color: {TEXT_COLOR}; }}
        
        /* FIX: Remove a ponta branca e uniformiza o input de data */
        div[data-testid="stDateInput"] > div {{
            background-color: transparent !important;
            border: none !important;
        }}
        
        div[data-testid="stDateInput"] div, 
        div[data-testid="stDateInput"] input {{
            background-color: {INPUT_BG} !important;
            color: {TEXT_COLOR} !important;
            border-radius: 8px !important;
        }}

        /* FIX: Calendário (Popover) totalmente escuro */
        div[data-baseweb="popover"] {{
            background-color: {BG_COLOR} !important;
            border: 1px solid {BORDER};
        }}
        
        div[data-baseweb="calendar"] {{
            background-color: {INPUT_BG} !important;
            color: {TEXT_COLOR} !important;
        }}

        /* Ajuste de Dropdowns (Selectbox) */
        div[data-baseweb="select"] > div {{
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
        
        /* Estilo para as métricas */
        [data-testid="stMetricValue"] {{ color: {TEXT_COLOR} !important; }}
    </style>
    """, unsafe_allow_html=True)

# Botão de Tema no canto superior
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
        lista_empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    except:
        lista_empresas = []
        
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    
    # Datas com formato brasileiro
    d_inicio = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown("<br><br>"*10, unsafe_allow_html=True)
    st.divider()
    # Checkbox invisível para Modo ADM
    modo_adm = st.checkbox("", label_visibility="collapsed")

# --- 5. INTERFACE PRINCIPAL ---
st.title("📊 Fluxo de Caixa BPO")

# Lógica ADM e Salvamento de Empresa (Funciona mesmo após o redirecionamento)
params = st.query_params
if modo_adm or "code" in params:
    with st.container(border=True):
        st.subheader("🔐 Gestão de Empresas")
        
        if "code" in params:
            st.success("✅ Autorização recebida da Conta Azul!")
            nome_nova = st.text_input("Nome da empresa para salvar:", key="input_nome_empresa")
            
            if st.button("Gravar Empresa na Planilha", type="primary"):
                if nome_nova:
                    resp = requests.post("https://auth.contaazul.com/oauth2/token",
                                        headers={"Authorization": f"Basic {B64_AUTH}"},
                                        data={"grant_type": "authorization_code", 
                                              "code": params["code"], 
                                              "redirect_uri": REDIRECT_URI})
                    if resp.status_code == 200:
                        get_sheet().append_row([nome_nova, resp.json()['refresh_token']])
                        st.success(f"Empresa '{nome_nova}' cadastrada!")
                        time.sleep(1.5)
                        st.query_params.clear()
                        st.rerun()
                    else:
                        st.error("Erro ao converter código em token. Tente novamente.")
                else:
                    st.warning("Digite um nome para a empresa.")
        else:
            pwd = st.text_input("Senha Master", type="password")
            if pwd == "8429coconoiaKc#":
                url_ca = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
                st.link_button("🔌 Conectar Nova Empresa", url_ca)

# --- 6. PROCESSAMENTO E GRÁFICOS ---
if st.button("🚀 Consultar Fluxo", type="primary"):
    all_data = []
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    
    if not alvos:
        st.warning("Nenhuma empresa cadastrada.")
    else:
        for emp in alvos:
            tk = get_access_token(emp)
            if tk:
                url = "https://api.contaazul.com/v1/financeiro/lancamentos"
                params_api = {
                    "data_inicio": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                    "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
                }
                res = requests.get(url, headers={"Authorization": f"Bearer {tk}"}, params=params_api)
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
            c1, c2, c3 = st.columns(3)
            c1.metric("A Receber", f"R$ {df_resumo['Receber'].sum():,.2f}")
            c2.metric("A Pagar", f"R$ {df_resumo['Pagar'].sum():,.2f}")
            c3.metric("Saldo Período", f"R$ {df_resumo['Saldo'].sum():,.2f}")
            
            # Gráfico
            fig = go.Figure()
            fig.add_trace(go.Bar(x=df_resumo['Data'], y=df_resumo['Receber'], name='Receber', marker_color='#00CC96'))
            fig.add_trace(go.Bar(x=df_resumo['Data'], y=-df_resumo['Pagar'], name='Pagar', marker_color='#EF553B'))
            fig.add_trace(go.Scatter(x=df_resumo['Data'], y=df_resumo['Acumulado'], name='Saldo Acumulado', line=dict(color='#34495e', width=3)))
            
            fig.update_layout(barmode='relative', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white")
            st.plotly_chart(fig, use_container_width=True)
            
            # Tabela
            df_tab = df_resumo.copy()
            df_tab['Data'] = df_tab['Data'].dt.strftime('%d/%m/%Y')
            st.dataframe(df_tab, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum lançamento encontrado para os filtros selecionados.")
