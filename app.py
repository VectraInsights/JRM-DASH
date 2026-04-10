import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

# Cores baseadas no tema
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "white" if st.session_state.theme == 'dark' else "#31333F"
input_bg = "#31333F" if st.session_state.theme == 'dark' else "#ffffff"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        [data-testid="stSidebar"] {{ background-color: {side_bg} !important; min-width: 300px; }}
        
        /* Correção dos menus de input no modo claro */
        [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div,
        [data-testid="stSidebar"] div[data-testid="stDateInput"] div {{
            background-color: {input_bg} !important;
            color: {txt} !important;
            border-radius: 5px;
        }}
        
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] label {{
            color: {txt} !important;
        }}

        [data-testid="stSidebar"] button {{
            border: none !important; background: transparent !important;
            box-shadow: none !important; font-size: 20px !important;
        }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. CREDENCIAIS E API ---
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

def refresh_access_token(refresh_token):
    url = "https://auth.contaazul.com/oauth2/token"
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data={"grant_type": "refresh_token", "refresh_token": refresh_token})
    return res.json().get("access_token") if res.status_code == 200 else None

# --- 3. CAPTURA DE RETORNO (CONTA AZUL) ---
# Esta parte precisa rodar antes da sidebar para interceptar o redirecionamento
q_params = st.query_params
if "code" in q_params:
    auth_code = q_params["code"]
    st.success("✅ Autenticação realizada! Agora dê um nome para esta empresa.")
    with st.container(border=True):
        nome_nova_emp = st.text_input("Nome da Empresa (ex: Juvenal Transportes)")
        if st.button("Salvar Empresa no Dashboard"):
            res = requests.post("https://auth.contaazul.com/oauth2/token", 
                                headers={"Authorization": f"Basic {B64_AUTH}"}, 
                                data={"grant_type": "authorization_code", "code": auth_code, "redirect_uri": REDIRECT_URI})
            if res.status_code == 200:
                new_refresh = res.json().get("refresh_token")
                sh = get_sheet()
                # Tenta atualizar se já existir ou cria nova linha
                try:
                    cell = sh.find(nome_nova_emp)
                    sh.update_cell(cell.row, 2, new_refresh)
                except:
                    sh.append_row([nome_nova_emp, new_refresh])
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Erro ao gerar token. Tente novamente.")

# --- 4. SIDEBAR ---
with st.sidebar:
    st.subheader("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    except:
        empresas = []

    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15), format="DD/MM/YYYY")
    
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.divider()
    c1, c2, _ = st.columns([0.2, 0.2, 0.6])
    with c1:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️"):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with c2:
        if st.button("🌓"):
            st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
            st.rerun()

# --- 5. ÁREA TÉCNICA (ADM) ---
st.title("📊 Fluxo de Caixa BPO")

if st.session_state.adm_mode:
    with st.expander("🔐 Área ADM", expanded=True):
        if st.text_input("Senha", type="password") == "8429coconoiaKc#":
            st.info("Para adicionar ou atualizar, clique no botão abaixo e faça login na Conta Azul.")
            st.link_button("🔗 Conectar Conta Azul", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 6. GRÁFICOS E DADOS ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_proc = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista_proc:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(row['refresh_token'])
        
        if token:
            for t in ["receivables", "payables"]:
                slug = 'contas-a-receber' if t=='receivables' else 'contas-a-pagar'
                url = f"https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/{slug}/buscar"
                params = {"data_vencimento_de": d_ini.strftime('%Y-%m-%d'), "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'), "tamanho_pagina": 500}
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params).json()
                
                for i in res.get("itens", []):
                    v = (i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 0.0)
                    dt = i.get('data_vencimento') or i.get('due_date')
                    data_points.append({
                        'Data': pd.to_datetime(dt),
                        'Tipo': 'Recebimentos' if t=='receivables' else 'Pagamentos',
                        'Valor': float(v)
                    })

    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        if 'Recebimentos' not in df_daily: df_daily['Recebimentos'] = 0
        if 'Pagamentos' not in df_daily: df_daily['Pagamentos'] = 0
        
        df_daily = df_daily.sort_values('Data')
        df_daily['Saldo_Acumulado'] = (df_daily['Recebimentos'] - df_daily['Pagamentos']).cumsum()
        df_daily['Data_Str'] = df_daily['Data'].dt.strftime('%d %b')

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data_Str'], y=df_daily['Recebimentos'], name='Recebimentos', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data_Str'], y=-df_daily['Pagamentos'], name='Pagamentos', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data_Str'], y=df_daily['Saldo_Acumulado'], name='Saldo', line=dict(color='#34495e', width=3)))

        fig.update_layout(barmode='relative', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white", height=450)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Saldo_Acumulado']], use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum lançamento no período.")
