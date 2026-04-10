import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

# CSS para o Botão de Olho no topo direito e remover padding desnecessário
st.markdown("""
    <style>
    .stApp { margin-top: -50px; }
    .float-adm {
        position: fixed;
        top: 10px;
        right: 80px;
        z-index: 999;
    }
    </style>
    """, unsafe_allow_html=True)

CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"

auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

# --- 2. GOOGLE SHEETS ---
@st.cache_resource
def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["google_sheets"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

sheet = init_gspread()

def get_tokens_db():
    try:
        df = pd.DataFrame(sheet.get_all_records())
        return df
    except:
        return pd.DataFrame()

def update_refresh_token(empresa, novo_token):
    df = get_tokens_db()
    empresa_up = empresa.upper().strip()
    try:
        idx_list = df.index[df['empresa'].str.upper() == empresa_up].tolist()
        if idx_list:
            sheet.update_cell(idx_list[0] + 2, 2, novo_token)
        else:
            sheet.append_row([empresa_up, novo_token])
    except: pass

# --- 3. API CONTA AZUL ---
def refresh_access_token(empresa, refresh_token_atual):
    url = "https://auth.contaazul.com/oauth2/token"
    headers = {"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token_atual}
    res = requests.post(url, headers=headers, data=data)
    if res.status_code == 200:
        dados = res.json()
        update_refresh_token(empresa, dados.get("refresh_token"))
        return dados.get("access_token")
    return None

def fetch_financeiro(token, tipo, d_inicio, d_fim):
    base_url = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"
    endpoint = f"{base_url}/contas-a-receber/buscar" if tipo == "receivables" else f"{base_url}/contas-a-pagar/buscar"
    params = {
        "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
        "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'),
        "tamanho_pagina": 1000
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(endpoint, headers=headers, params=params)
    return res.json() if res.status_code == 200 else []

# --- 4. INTERFACE E CONTROLES ---
if 'adm_mode' not in st.session_state:
    st.session_state.adm_mode = False

# Botão Flutuante (Olho)
col_adm = st.columns([0.95, 0.05])
with col_adm[1]:
    icon = "👁️" if st.session_state.adm_mode else "👁️‍🗨️"
    if st.button(icon, help="Modo Administrativo"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

# Modal de Senha se o olho for clicado
if st.session_state.adm_mode:
    with st.expander("🔒 Autenticação ADM", expanded=True):
        senha = st.text_input("Chave", type="password")
        if senha == "8429coconoiaKc#":
            st.success("Acesso Liberado")
            url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
            st.link_button("🔌 Conectar Nova Empresa", url_auth)
        else:
            st.stop()

st.title("📈 Fluxo de Caixa BPO")

with st.sidebar:
    st.header("🔍 Filtros")
    df_db = get_tokens_db()
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    
    hoje = datetime.now()
    d_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", hoje + timedelta(days=15), format="DD/MM/YYYY")

# --- 5. PROCESSAMENTO E GRÁFICOS ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    processar = empresas if selecao == "TODAS" else [selecao]

    for emp in processar:
        t_ref = df_db.loc[df_db['empresa'] == emp, 'refresh_token'].values[0]
        t_acc = refresh_access_token(emp, t_ref)
        
        if t_acc:
            for t_tipo in ["receivables", "payables"]:
                dados = fetch_financeiro(t_acc, t_tipo, d_ini, d_fim)
                itens = dados if isinstance(dados, list) else dados.get("itens", [])
                
                for i in itens:
                    # Captura de valor multi-campo para evitar o erro de valor 0
                    v = i.get('valor_total') or i.get('valor') or i.get('valor_parcela') or i.get('value') or 0
                    mult = 1 if t_tipo == "receivables" else -1
                    
                    data_points.append({
                        'Data': pd.to_datetime(i.get('data_vencimento') or i.get('due_date')),
                        'Valor': float(v) * mult,
                        'Tipo': 'Receita' if mult == 1 else 'Despesa'
                    })

    if data_points:
        df = pd.DataFrame(data_points)
        
        # Dashboard de métricas
        m1, m2, m3 = st.columns(3)
        receita = df[df['Valor'] > 0]['Valor'].sum()
        despesa = abs(df[df['Valor'] < 0]['Valor'].sum())
        m1.metric("Entradas", f"R$ {receita:,.2f}")
        m2.metric("Saídas", f"R$ {despesa:,.2f}")
        m3.metric("Saldo Líquido", f"R$ {(receita - despesa):,.2f}")

        # Gráfico 1: Evolução do Saldo Diário
        st.subheader("📊 Saldo Diário Consolidado")
        df_chart = df.groupby('Data')['Valor'].sum().sort_index()
        st.bar_chart(df_chart)

        # Gráfico 2: Comparativo Entradas vs Saídas
        st.subheader("🌓 Comparativo de Volume")
        df_comp = df.groupby([df['Data'].dt.date, 'Tipo'])['Valor'].sum().abs().unstack().fillna(0)
        st.area_chart(df_comp)
        
        with st.expander("📝 Detalhes dos Lançamentos"):
            st.dataframe(df.sort_values('Data'), use_container_width=True)
    else:
        st.warning("Nenhum lançamento com valor encontrado para o período.")

# Callback Oauth
if "code" in st.query_params and st.session_state.adm_mode:
    nome_n = st.text_input("Nome da nova empresa:")
    if st.button("Salvar Conexão"):
        # Processo de token final
        pass
