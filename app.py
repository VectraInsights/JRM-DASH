import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go
import time

# --- CONFIGURAÇÃO INICIAL ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

# CSS Unificado (Modo Claro/Escuro e Botões)
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        .floating-theme {{ position: fixed; top: 10px; right: 15px; z-index: 999999; }}
        .floating-theme button {{ background: transparent !important; border: 1px solid #888 !important; border-radius: 5px; }}
        .debug-container {{ border: 2px solid #ff4b4b; padding: 15px; border-radius: 10px; margin-top: 10px; background-color: rgba(255, 75, 75, 0.05); }}
    </style>
    """, unsafe_allow_html=True)

# Botão de Tema
st.markdown('<div class="floating-theme">', unsafe_allow_html=True)
if st.button("🌓", key="theme_toggle"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- INTEGRAÇÕES ---
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
            sh.update_cell(cell.row, 2, data['refresh_token'])
            return data['access_token']
        return None
    except:
        return None

# --- INTERFACE ---
with st.sidebar:
    st.title("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas_list = df_db['empresa'].unique().tolist()
    except:
        empresas_list = []
        
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas_list)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown('<br><br>' * 10, unsafe_allow_html=True)
    if st.button("👁️", key="adm_eye"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

st.title("📊 Fluxo de Caixa BPO")

# Área Administrativa
if st.session_state.adm_mode:
    with st.container(border=True):
        st.subheader("🔑 Área Administrativa")
        if st.text_input("Senha", type="password") == "8429coconoiaKc#":
            st.link_button("🔌 Reconectar Empresa (Gerar Novo Token)", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")
            
            if "code" in st.query_params:
                nome_fina = st.text_input("Nome da empresa para atualizar:")
                if st.button("Salvar"):
                    r = requests.post("https://auth.contaazul.com/oauth2/token", headers={"Authorization": f"Basic {B64_AUTH}"},
                                      data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
                    if r.status_code == 200:
                        sh = get_sheet()
                        try:
                            cell = sh.find(nome_fina)
                            sh.update_cell(cell.row, 2, r.json()['refresh_token'])
                        except:
                            sh.append_row([nome_fina, r.json()['refresh_token']])
                        st.success("Token Atualizado!")
                        st.query_params.clear()
                        st.rerun()

# Botão de Consulta
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    with st.expander("🛠️ Log de Depuração", expanded=True):
        st.markdown('<div class="debug-container">', unsafe_allow_html=True)
        for emp in lista_alvo:
            st.write(f"🔍 Verificando: **{emp}**")
            token = get_new_access_token(emp)
            
            if not token:
                st.error(f"❌ Token Inválido para {emp}. Use o Modo ADM para reconectar.")
                continue

            res = requests.get("https://api.contaazul.com/v1/financeiro/lancamentos", 
                               headers={"Authorization": f"Bearer {token}"},
                               params={"data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'), 
                                       "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')})
            
            if res.status_code == 200:
                itens = res.json()
                st.write(f"✅ {len(itens)} lançamentos encontrados.")
                for l in itens:
                    data_points.append({
                        'Data': pd.to_datetime(l.get('data_vencimento')).date(),
                        'Tipo': 'Receber' if l.get('tipo') == 'RECEBER' else 'Pagar',
                        'Valor': float(l.get('valor', 0))
                    })
            else:
                st.error(f"❌ Erro {res.status_code} na API da Conta Azul para {emp}.")
        st.markdown('</div>', unsafe_allow_html=True)

    if data_points:
        df = pd.DataFrame(data_points)
        df_resumo = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        st.dataframe(df_resumo, use_container_width=True)
