import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES E TEMA DINÂMICO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state:
    st.session_state.theme = 'auto' # Segue o sistema por padrão

# CSS para os botões e Alternância de Tema
dark_style = """
    <style>
        .stApp { background-color: #0e1117; color: white; }
        header { visibility: hidden; }
    </style>
"""
light_style = """
    <style>
        .stApp { background-color: white; color: black; }
        header { visibility: hidden; }
    </style>
"""

if st.session_state.theme == 'dark':
    st.markdown(dark_style, unsafe_allow_html=True)
elif st.session_state.theme == 'light':
    st.markdown(light_style, unsafe_allow_html=True)

# --- 2. CREDENCIAIS ---
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

# --- 3. GOOGLE SHEETS E API ---
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

def refresh_access_token(empresa, refresh_token_atual):
    url = "https://auth.contaazul.com/oauth2/token"
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token_atual}
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data=data)
    if res.status_code == 200:
        novo = res.json().get("refresh_token")
        # Atualização silenciosa no Sheets aqui se necessário
        return res.json().get("access_token")
    return None

def fetch_financeiro(token, tipo, d_inicio, d_fim):
    base = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"
    endpoint = f"{base}/contas-a-receber/buscar" if tipo == "receivables" else f"{base}/contas-a-pagar/buscar"
    params = {"data_vencimento_de": d_inicio.strftime('%Y-%m-%d'), "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'), "tamanho_pagina": 1000}
    res = requests.get(endpoint, headers={"Authorization": f"Bearer {token}"}, params=params)
    return res.json() if res.status_code == 200 else {}

# --- 4. CABEÇALHO (BOTÕES PEQUENOS NO TOPO) ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

c_vazio, c_btn1, c_btn2 = st.columns([0.92, 0.04, 0.04])
with c_btn1:
    if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()
with c_btn2:
    if st.button("🌓"):
        st.session_state.theme = 'light' if st.session_state.theme != 'light' else 'dark'
        st.rerun()

if st.session_state.adm_mode:
    with st.expander("Área ADM"):
        senha = st.text_input("Senha", type="password")
        if senha == "8429coconoiaKc#":
            st.link_button("Conectar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 5. INTERFACE PRINCIPAL ---
st.title("📈 Fluxo de Caixa BPO")

with st.sidebar:
    df_db = get_tokens_db()
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now())
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15))

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    processar = empresas if selecao == "TODAS" else [selecao]
    
    for emp in processar:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(emp, row['refresh_token'])
        if token:
            for t in ["receivables", "payables"]:
                res = fetch_financeiro(token, t, d_ini, d_fim)
                itens = res.get("itens", [])
                for i in itens:
                    # RASTREAMENTO DO VALOR: Tentando todas as chaves possíveis da v2
                    v = i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 0
                    mult = 1 if t == "receivables" else -1
                    data_points.append({
                        'Data': pd.to_datetime(i.get('data_vencimento') or i.get('due_date')),
                        'Valor': float(v) * mult,
                        'Tipo': 'Receita' if mult == 1 else 'Despesa',
                        'Empresa': emp
                    })

    if data_points:
        df = pd.DataFrame(data_points)
        
        # Métricas
        m1, m2, m3 = st.columns(3)
        rec = df[df['Valor'] > 0]['Valor'].sum()
        des = abs(df[df['Valor'] < 0]['Valor'].sum())
        m1.metric("Entradas", f"R$ {rec:,.2f}")
        m2.metric("Saídas", f"R$ {des:,.2f}")
        m3.metric("Saldo", f"R$ {(rec - des):,.2f}")

        # Gráfico
        st.bar_chart(df.groupby('Data')['Valor'].sum())

        with st.expander("📄 Detalhes dos Lançamentos", expanded=True):
            # Formatação da Tabela conforme pedido: Sem índice, Data limpa
            df_view = df.copy()
            df_view['Data'] = df_view['Data'].dt.strftime('%d/%m/%Y')
            # Organizando colunas
            df_view = df_view[['Data', 'Empresa', 'Tipo', 'Valor']]
            st.dataframe(df_view, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado encontrado.")
