import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

# CSS para esconder menus, limpar a UI e formatar botões da sidebar
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        div.block-container {padding-top: 2rem;}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.5rem; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. CREDENCIAIS E TOKENS ---
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

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
    headers = {"Authorization": f"Basic {B64_AUTH}"}
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token_atual}
    res = requests.post(url, headers=headers, data=data)
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
    return res.json() if res.status_code == 200 else {}

# --- 3. BARRA LATERAL (FILTROS + BOTÕES FINAIS) ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

with st.sidebar:
    st.title("⚙️ Filtros")
    df_db = get_tokens_db()
    lista_empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15), format="DD/MM/YYYY")
    
    # Espaçador para empurrar os botões para baixo
    st.markdown("<br><br>" * 5, unsafe_allow_html=True)
    st.divider()
    
    # Botões Alinhados no fim da sidebar
    col_adm, col_theme = st.columns(2)
    with col_adm:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️", use_container_width=True):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with col_theme:
        if st.button("🌓", use_container_width=True):
            # Alterna o tema via config de query (mais estável)
            st.toast("Alternando visual...")

# Área administrativa condicional
if st.session_state.adm_mode:
    with st.expander("Área ADM", expanded=True):
        senha = st.text_input("Senha", type="password")
        if senha == "8429coconoiaKc#":
            st.link_button("Conectar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 4. CONTEÚDO PRINCIPAL ---
st.title("📉 Fluxo de Caixa BPO")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_proc = lista_empresas if selecao == "TODAS" else [selecao]
    
    prog = st.progress(0)
    for idx, emp in enumerate(lista_proc):
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(emp, row['refresh_token'])
        
        if token:
            for t in ["receivables", "payables"]:
                res = fetch_financeiro(token, t, d_ini, d_fim)
                itens = res.get("itens", [])
                for i in itens:
                    # Tenta pegar valor de qualquer campo numérico disponível
                    val = i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 0
                    mult = 1 if t == "receivables" else -1
                    data_points.append({
                        'Data': pd.to_datetime(i.get('data_vencimento') or i.get('due_date')),
                        'Valor': float(val) * mult,
                        'Tipo': 'Receita' if mult == 1 else 'Despesa',
                        'Empresa': emp
                    })
        prog.progress((idx + 1) / len(lista_proc))

    if data_points:
        df = pd.DataFrame(data_points)
        
        # Métricas
        c1, c2, c3 = st.columns(3)
        receitas = df[df['Valor'] > 0]['Valor'].sum()
        despesas = abs(df[df['Valor'] < 0]['Valor'].sum())
        c1.metric("Previsto Entradas", f"R$ {receitas:,.2f}")
        c2.metric("Previsto Saídas", f"R$ {despesas:,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(receitas - despesas):,.2f}")

        # Tabela Detalhada
        st.subheader("📄 Detalhes dos Lançamentos")
        df_final = df.copy()
        df_final['Data'] = df_final['Data'].dt.strftime('%d/%m/%Y')
        df_final = df_final[['Data', 'Empresa', 'Tipo', 'Valor']]
        
        st.dataframe(
            df_final.sort_values('Data', ascending=True), 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.warning("Nenhum dado encontrado para o período/empresa selecionada.")
