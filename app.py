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

# --- CONFIGURAÇÃO DE IDIOMA (Para o Calendário) ---
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.utf8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil.1252')
    except:
        pass # Mantém o padrão se o servidor não suportar

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'

# Cores do Tema
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"
input_fill = "#1e1e1e" if st.session_state.theme == 'dark' else "#ffffff"
border_color = "#444" if st.session_state.theme == 'dark' else "#ccc"

# --- 2. CSS AVANÇADO (Dropdown e Calendário) ---
st.markdown(f"""
    <style>
        header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        
        /* Estilização do DROPDOWN (BaseWeb Popover) */
        div[data-baseweb="popover"], div[data-baseweb="listbox"] {{
            background-color: {input_fill} !important;
        }}
        div[data-baseweb="popover"] li {{
            background-color: {input_fill} !important;
            color: {txt} !important;
        }}
        div[data-baseweb="popover"] li:hover {{
            background-color: #444 !important;
        }}

        /* Estilização do CALENDÁRIO */
        div[role="dialog"] {{
            background-color: {input_fill} !important;
            color: {txt} !important;
        }}

        /* Barra Lateral */
        [data-testid="stSidebar"] {{ background-color: {side_bg} !important; border-right: 1px solid {border_color}; }}
        
        /* Botão de Tema Fixo */
        .theme-btn-container {{ position: fixed; top: 15px; right: 15px; z-index: 999999; }}
    </style>
    """, unsafe_allow_html=True)

st.markdown('<div class="theme-btn-container">', unsafe_allow_html=True)
if st.button("🌓", key="theme_toggle"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- 3. INTEGRAÇÕES ---
# (Certifique-se que estas chaves existem no seu Secrets)
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
            # Atualiza o refresh token na planilha para a próxima vez
            sh.update_cell(cell.row, 2, data.get("refresh_token"))
            return data.get("access_token")
        else:
            st.error(f"Erro Refresh Token ({empresa}): {res.text}")
            return None
    except Exception as e:
        st.error(f"Erro ao buscar empresa '{empresa}' na planilha: {e}")
        return None

# --- 4. BARRA LATERAL ---
with st.sidebar:
    st.title("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    except:
        empresas_list = []
        st.warning("Não foi possível carregar a lista de empresas.")
        
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas_list)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown('<div style="height: 50vh;"></div>', unsafe_allow_html=True)
    st.divider()
    adm_mode = st.checkbox("", key="adm_check", label_visibility="collapsed")

# --- 5. INTERFACE PRINCIPAL ---
st.title("📊 Fluxo de Caixa BPO")

if adm_mode:
    with st.expander("🔑 Área Administrativa", expanded=True):
        pwd = st.text_input("Senha", type="password")
        if pwd == "8429coconoiaKc#":
            st.link_button("🔌 Conectar Nova Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 6. CONSULTA ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    for emp in lista_alvo:
        token = get_new_access_token(emp)
        if token:
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            params = {
                "data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'), 
                "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
            }
            res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            
            if res.status_code == 200:
                dados = res.json()
                for lanc in dados:
                    data_points.append({
                        'Data': pd.to_datetime(lanc.get('data_vencimento')),
                        'Tipo': 'Recebimentos' if lanc.get('tipo') == 'RECEBER' else 'Pagamentos',
                        'Valor': float(lanc.get('valor', 0))
                    })
            else:
                st.error(f"Erro na API ({emp}): {res.status_code} - {res.text}")
    
    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        
        # Garante colunas
        for c in ['Recebimentos', 'Pagamentos']:
            if c not in df_daily.columns: df_daily[c] = 0.0
            
        df_daily['Saldo Diário'] = df_daily['Recebimentos'] - df_daily['Pagamentos']
        df_daily['Acumulado'] = df_daily['Saldo Diário'].cumsum()

        # Gráfico e Métricas
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {df_daily['Recebimentos'].sum():,.2f}")
        c2.metric("Total a Pagar", f"R$ {df_daily['Pagamentos'].sum():,.2f}")
        c3.metric("Saldo Período", f"R$ {df_daily['Saldo Diário'].sum():,.2f}")

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data'], y=df_daily['Recebimentos'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data'], y=-df_daily['Pagamentos'], name='Pagar', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data'], y=df_daily['Acumulado'], name='Saldo Acumulado', line=dict(color='#34495e', width=3)))
        fig.update_layout(barmode='relative', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Nenhum dado retornado para o período selecionado.")
