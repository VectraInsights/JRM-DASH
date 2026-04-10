import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES E TEMA ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

# CSS para fixar os botões no topo direito e deixá-los pequenos
st.markdown("""
    <style>
    .stApp { margin-top: -60px; }
    div[data-testid="stColumn"] > div > button {
        padding: 2px 10px;
        font-size: 14px;
        border-radius: 20px;
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
        return pd.DataFrame(sheet.get_all_records())
    except:
        return pd.DataFrame()

def update_refresh_token(empresa, novo_token):
    df = get_tokens_db()
    empresa_up = empresa.upper().strip()
    try:
        idx_list = df.index[df['empresa'].str.upper() == empresa_up].tolist()
        if idx_list: sheet.update_cell(idx_list[0] + 2, 2, novo_token)
        else: sheet.append_row([empresa_up, novo_token])
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
    try:
        res = requests.get(endpoint, headers=headers, params=params, timeout=10)
        return res.json() if res.status_code == 200 else {}
    except: return {}

# --- 4. HEADER COM BOTÕES (ADM E TEMA) ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

# Grid para botões no topo direito
head_l, head_r = st.columns([0.88, 0.12])
with head_r:
    sub_c1, sub_c2 = st.columns(2)
    with sub_c1:
        # Ícone do Olho (ADM)
        icon_adm = "👁️" if st.session_state.adm_mode else "👁️‍🗨️"
        if st.button(icon_adm):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with sub_c2:
        # Ícone do Tema (Simulado via HTML/JS para ser discreto)
        if st.button("🌓"):
            st.toast("Mude o tema nas configurações do navegador ou sistema")

# Conteúdo Administrativo
if st.session_state.adm_mode:
    with st.expander("🔑 Área Administrativa", expanded=True):
        senha = st.text_input("Chave", type="password")
        if senha == "8429coconoiaKc#":
            st.link_button("🔌 Vincular Nova Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")
        else: st.stop()

# --- 5. DASHBOARD PRINCIPAL ---
st.title("📈 Fluxo de Caixa BPO")

with st.sidebar:
    st.header("🔍 Filtros")
    df_db = get_tokens_db()
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    
    hoje = datetime.now()
    d_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", hoje + timedelta(days=15), format="DD/MM/YYYY")

# --- 6. GERAÇÃO DE FLUXO ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    processar = empresas if selecao == "TODAS" else [selecao]
    
    progresso = st.progress(0)
    for idx, emp in enumerate(processar):
        try:
            row = df_db[df_db['empresa'] == emp].iloc[0]
            t_acc = refresh_access_token(emp, row['refresh_token'])
            
            if t_acc:
                for tipo in ["receivables", "payables"]:
                    res = fetch_financeiro(t_acc, tipo, d_ini, d_fim)
                    itens = res.get("itens", []) if isinstance(res, dict) else []
                    
                    for i in itens:
                        # Busca agressiva por valor[cite: 8]
                        v = i.get('valor_total') or i.get('valor_parcela') or i.get('valor') or i.get('value') or 0
                        mult = 1 if tipo == "receivables" else -1
                        data_points.append({
                            'Data': pd.to_datetime(i.get('data_vencimento') or i.get('due_date')),
                            'Valor': float(v) * mult,
                            'Tipo': 'Receita' if mult == 1 else 'Despesa',
                            'Empresa': emp
                        })
        except: continue
        progresso.progress((idx + 1) / len(processar))

    if data_points:
        df = pd.DataFrame(data_points)
        
        # Métricas
        c1, c2, c3 = st.columns(3)
        rec = df[df['Valor'] > 0]['Valor'].sum()
        des = abs(df[df['Valor'] < 0]['Valor'].sum())
        c1.metric("Previsto Entradas", f"R$ {rec:,.2f}")
        c2.metric("Previsto Saídas", f"R$ {des:,.2f}", delta_color="inverse")
        c3.metric("Saldo Líquido", f"R$ {(rec - des):,.2f}")

        # Gráfico Diário
        st.subheader("📊 Saldo Diário do Período")
        df_diario = df.groupby('Data')['Valor'].sum().sort_index()
        st.bar_chart(df_diario)

        with st.expander("📄 Detalhes dos Lançamentos"):
            st.dataframe(df.sort_values('Data'), use_container_width=True)
    else:
        st.warning("Nenhum lançamento encontrado. Verifique se as empresas estão conectadas.")
