import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES E OCULTAR MENUS ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        div.block-container {padding-top: 1rem;}
        [data-testid="stSidebar"] {background-color: #111;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONFIGURAÇÕES DE API ---
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"

auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

# --- 3. GOOGLE SHEETS ---
@st.cache_resource
def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["google_sheets"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

sheet = init_gspread()

def get_tokens_db():
    try: return pd.DataFrame(sheet.get_all_records())
    except: return pd.DataFrame()

# --- 4. LÓGICA DE API E DEPURAÇÃO ---
def refresh_access_token(empresa, refresh_token_atual):
    url = "https://auth.contaazul.com/oauth2/token"
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token_atual}
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data=data)
    if res.status_code == 200:
        return res.json().get("access_token")
    return None

def fetch_financeiro(token, tipo, d_inicio, d_fim):
    base = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"
    end = f"{base}/contas-a-receber/buscar" if tipo == "receivables" else f"{base}/contas-a-pagar/buscar"
    params = {
        "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
        "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'),
        "tamanho_pagina": 1000
    }
    res = requests.get(end, headers={"Authorization": f"Bearer {token}"}, params=params)
    return res.status_code, res.json()

# --- 5. BARRA LATERAL ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

with st.sidebar:
    st.subheader("Filtros")
    df_db = get_tokens_db()
    lista_empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    
    d_ini = st.date_input("Início", datetime.now())
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15))
    
    # Empurra botões para o final
    st.write("---")
    col_adm, col_theme = st.columns(2)
    with col_adm:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️", use_container_width=True):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with col_theme:
        if st.button("🌓", use_container_width=True):
            st.toast("Alternando tema...")

if st.session_state.adm_mode:
    with st.expander("🔐 ADM", expanded=True):
        senha = st.text_input("Chave", type="password")
        if senha == "8429coconoiaKc#":
            st.link_button("Conectar Nova Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 6. PROCESSAMENTO ---
st.title("📈 Fluxo de Caixa BPO")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    debug_logs = []
    lista_proc = lista_empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista_proc:
        try:
            row = df_db[df_db['empresa'] == emp].iloc[0]
            token = refresh_access_token(emp, row['refresh_token'])
            
            if token:
                for t in ["receivables", "payables"]:
                    status, res = fetch_financeiro(token, t, d_ini, d_fim)
                    itens = res.get("itens", []) if isinstance(res, dict) else []
                    
                    # Salva log de depuração se estiver vazio
                    if not itens:
                        debug_logs.append(f"Empresa: {emp} | Tipo: {t} | Status: {status} | Resposta: {res}")
                    
                    for i in itens:
                        # Varredura de valor em campos possíveis
                        val = i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 0
                        mult = 1 if t == "receivables" else -1
                        data_points.append({
                            'Data': pd.to_datetime(i.get('data_vencimento') or i.get('due_date')),
                            'Valor': float(val) * mult,
                            'Tipo': 'Receita' if mult == 1 else 'Despesa',
                            'Empresa': emp
                        })
            else:
                debug_logs.append(f"Falha ao renovar token para: {emp}")
        except Exception as e:
            debug_logs.append(f"Erro crítico em {emp}: {str(e)}")

    if data_points:
        df = pd.DataFrame(data_points)
        
        # Métricas
        c1, c2, c3 = st.columns(3)
        rec = df[df['Valor'] > 0]['Valor'].sum()
        des = abs(df[df['Valor'] < 0]['Valor'].sum())
        c1.metric("Entradas", f"R$ {rec:,.2f}")
        c2.metric("Saídas", f"R$ {des:,.2f}")
        c3.metric("Saldo", f"R$ {(rec - des):,.2f}")

        # Tabela Detalhada
        df_view = df.copy()
        df_view['Data'] = df_view['Data'].dt.strftime('%d/%m/%Y')
        df_view = df_view[['Data', 'Empresa', 'Tipo', 'Valor']]
        st.dataframe(df_view.sort_values('Data'), use_container_width=True, hide_index=True)
    else:
        st.error("Nenhum dado encontrado.")
        with st.expander("🛠️ Ver Depuração Técnica"):
            for log in debug_logs: st.code(log)
