import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

# Inicialização do estado do tema
if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

# CSS para esconder lixo da UI, formatar botões pequenos e injetar tema
theme_bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
theme_txt = "white" if st.session_state.theme == 'dark' else "black"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {theme_bg}; color: {theme_txt}; }}
        
        /* Botões da Sidebar Minimalistas */
        [data-testid="stSidebar"] button {{
            border: none !important;
            background: transparent !important;
            padding: 0 !important;
            width: auto !important;
            box-shadow: none !important;
            font-size: 20px !important;
        }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONFIGURAÇÕES API ---
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
B64_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

@st.cache_resource
def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

def refresh_access_token(empresa, refresh_token_atual):
    url = "https://auth.contaazul.com/oauth2/token"
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token_atual}
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data=data)
    return res.json().get("access_token") if res.status_code == 200 else None

def fetch_financeiro(token, tipo, d_inicio, d_fim):
    base = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"
    end = f"{base}/contas-a-receber/buscar" if tipo == "receivables" else f"{base}/contas-a-pagar/buscar"
    params = {"data_vencimento_de": d_inicio.strftime('%Y-%m-%d'), "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'), "tamanho_pagina": 1000}
    res = requests.get(end, headers={"Authorization": f"Bearer {token}"}, params=params)
    return res.status_code, res.json()

# --- 3. SIDEBAR ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(init_gspread().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15), format="DD/MM/YYYY")
    
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.divider()
    
    # Botões pequenos e sem caixa
    c1, c2, _ = st.columns([0.2, 0.2, 0.6])
    with c1:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️"):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with c2:
        if st.button("🌓"):
            st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
            st.rerun()

if st.session_state.adm_mode:
    with st.expander("Área Técnica", expanded=True):
        if st.text_input("Chave", type="password") == "8429coconoiaKc#":
            st.link_button("Reconectar Tokens", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 4. FLUXO DE CAIXA ---
st.title("📈 Fluxo de Caixa BPO")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    logs = []
    lista_proc = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista_proc:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(emp, row['refresh_token'])
        
        if token:
            for t in ["receivables", "payables"]:
                status, res = fetch_financeiro(token, t, d_ini, d_fim)
                itens = res.get("itens", []) if isinstance(res, dict) else []
                for i in itens:
                    val = i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 0
                    mult = 1 if t == "receivables" else -1
                    # Data formatada IMEDIATAMENTE para evitar erros de padrão
                    dt_obj = pd.to_datetime(i.get('data_vencimento') or i.get('due_date'))
                    data_points.append({
                        'Data': dt_obj.strftime('%d/%m/%Y'),
                        'Empresa': emp,
                        'Tipo': 'Receita' if mult == 1 else 'Despesa',
                        'Valor': float(val) * mult
                    })
        else:
            logs.append(f"❌ Falha no token: {emp} (Necessário reconectar)")

    if data_points:
        df = pd.DataFrame(data_points)
        c1, c2, c3 = st.columns(3)
        rec = df[df['Valor'] > 0]['Valor'].sum()
        des = abs(df[df['Valor'] < 0]['Valor'].sum())
        c1.metric("Entradas", f"R$ {rec:,.2f}")
        c2.metric("Saídas", f"R$ {des:,.2f}")
        c3.metric("Saldo", f"R$ {(rec - des):,.2f}")

        st.dataframe(df, use_container_width=True, hide_index=True)
    
    if logs:
        with st.expander("Logs de Erro"):
            for l in logs: st.error(l)
