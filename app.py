import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "white" if st.session_state.theme == 'dark' else "#31333F"
input_fill = "#1e1e1e" if st.session_state.theme == 'dark' else "#ffffff"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        [data-testid="stSidebar"] {{ background-color: {side_bg} !important; }}
        
        /* Botão de Tema minimalista no canto superior direito */
        .st-emotion-cache-12fmjuu {{ display: none; }} /* Esconde menu original se houver */
        .floating-theme {{
            position: fixed;
            top: 12px;
            right: 15px;
            z-index: 999999;
        }}
        .floating-theme button {{
            background: transparent !important;
            border: none !important;
            font-size: 14px !important;
            opacity: 0.5;
        }}
        .floating-theme button:hover {{ opacity: 1; }}

        /* Ajuste Sidebar */
        [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"],
        [data-testid="stSidebar"] .stDateInput div {{ background-color: {input_fill} !important; color: {txt} !important; }}
        
        .spacer {{ height: 100vh; }} /* Força rolagem longa para o olho */
    </style>
    """, unsafe_allow_html=True)

# Botão de Tema no local solicitado
st.markdown('<div class="floating-theme">', unsafe_allow_html=True)
if st.button("🌓", key="theme_toggle"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- 2. API & GOOGLE SHEETS ---
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

def update_refresh_token_in_sheet(empresa_nome, new_refresh_token):
    sh = get_sheet()
    try:
        cell = sh.find(empresa_nome)
        sh.update_cell(cell.row, 2, new_refresh_token)
    except:
        sh.append_row([empresa_nome, new_refresh_token])

def get_tokens(refresh_token, empresa_nome):
    url = "https://auth.contaazul.com/oauth2/token"
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, 
                        data={"grant_type": "refresh_token", "refresh_token": refresh_token})
    if res.status_code == 200:
        data = res.json()
        new_rt = data.get("refresh_token")
        if new_rt:
            update_refresh_token_in_sheet(empresa_nome, new_rt)
        return data.get("access_token")
    return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown('<div class="spacer"></div>', unsafe_allow_html=True)
    if st.button("👁️", key="adm_eye"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

# --- 4. ÁREA ADM & CONSULTA ---
st.title("📊 Fluxo de Caixa BPO")

# Captura de código da URL (Login Conta Azul)
if "code" in st.query_params:
    with st.status("Registrando nova empresa..."):
        r = requests.post("https://auth.contaazul.com/oauth2/token", headers={"Authorization": f"Basic {B64_AUTH}"},
                          data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
        if r.status_code == 200:
            st.success("Conectado! Nomeie a empresa na Área ADM.")
            # Aqui você pode salvar com um nome genérico e depois renomear na planilha
            update_refresh_token_in_sheet("NOVA_EMPRESA_PENDENTE", r.json().get("refresh_token"))
            st.query_params.clear()

if st.session_state.adm_mode:
    with st.expander("🔑 Configurações", expanded=True):
        if st.text_input("Acesso", type="password") == "8429coconoiaKc#":
            st.link_button("🔌 Conectar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        acc_token = get_tokens(row['refresh_token'], emp)
        
        if acc_token:
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            params_api = {
                "data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'),
                "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
            }
            res = requests.get(url, headers={"Authorization": f"Bearer {acc_token}"}, params=params_api)
            
            if res.status_code == 200:
                for lanc in res.json():
                    # Proteção contra erros de atributo
                    if isinstance(lanc, dict):
                        v = lanc.get('valor', 0)
                        tp = lanc.get('tipo')
                        dt = lanc.get('data_vencimento')
                        
                        if dt and tp:
                            data_points.append({
                                'Data': pd.to_datetime(dt).date(),
                                'Tipo': 'Recebimentos' if tp == 'RECEBER' else 'Pagamentos',
                                'Valor': float(v)
                            })

    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Recebimentos', 'Pagamentos']:
            if col not in df_daily: df_daily[col] = 0
        
        df_daily = df_daily.sort_values('Data')
        df_daily['Saldo_Acumulado'] = (df_daily['Recebimentos'] - df_daily['Pagamentos']).cumsum()
        df_daily['Data_Grafico'] = df_daily['Data'].apply(lambda x: x.strftime('%d/%m'))

        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {df_daily['Recebimentos'].sum():,.2f}")
        c2.metric("Total a Pagar", f"R$ {df_daily['Pagamentos'].sum():,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(df_daily['Recebimentos'].sum() - df_daily['Pagamentos'].sum()):,.2f}")

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=df_daily['Recebimentos'], name='Recebimentos', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=df_daily['Pagamentos'], name='Pagamentos', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data_Grafico'], y=df_daily['Saldo_Acumulado'], name='Saldo Acumulado', line=dict(color='#34495e', width=4)))
        
        fig.update_layout(barmode='group', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
                          legend=dict(orientation="h", y=-0.2), height=500)
        st.plotly_chart(fig, use_container_width=True)

        df_tab = df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Saldo_Acumulado']].copy()
        df_tab['Data'] = df_tab['Data'].apply(lambda x: x.strftime('%d/%m/%Y'))
        st.dataframe(df_tab, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado financeiro encontrado para este período.")
