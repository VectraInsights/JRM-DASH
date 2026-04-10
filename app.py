import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'

# Cores dinâmicas para o tema
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "white" if st.session_state.theme == 'dark' else "black"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        [data-testid="stSidebar"] button {{
            border: none !important; background: transparent !important;
            padding: 0 !important; width: auto !important;
            box-shadow: none !important; font-size: 20px !important;
        }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONFIGURAÇÕES API & GOOGLE SHEETS ---
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
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data=data)
    return res.json().get("access_token") if res.status_code == 200 else None

# --- 3. LÓGICA DE SALVAMENTO (NOVO) ---
def salvar_nova_empresa(auth_code):
    url = "https://auth.contaazul.com/oauth2/token"
    data = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI
    }
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data=data)
    if res.status_code == 200:
        dados = res.json()
        refresh_token = dados.get("refresh_token")
        # Busca o nome da empresa na API para salvar
        acc_token = dados.get("access_token")
        me = requests.get("https://api-v2.contaazul.com/v1/info", headers={"Authorization": f"Bearer {acc_token}"}).json()
        nome_empresa = me.get("name", "Nova Empresa")
        
        sheet = get_sheet()
        sheet.append_row([nome_empresa, refresh_token])
        st.success(f"✅ Empresa '{nome_empresa}' salva com sucesso!")
    else:
        st.error("Erro ao trocar código pelo token. Verifique as credenciais.")

# --- 4. SIDEBAR ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now())
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15))
    
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

# --- 5. VERIFICAÇÃO DE RETORNO DO LOGIN (OAUTH) ---
query_params = st.query_params
if "code" in query_params:
    auth_code = query_params["code"]
    salvar_nova_empresa(auth_code)
    st.query_params.clear() # Limpa a URL após salvar

if st.session_state.adm_mode:
    with st.expander("Área Técnica", expanded=True):
        if st.text_input("Chave", type="password") == "8429coconoiaKc#":
            st.link_button("🔗 Conectar/Atualizar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 6. EXECUÇÃO ---
st.title("📈 Fluxo de Caixa BPO")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_proc = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista_proc:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(row['refresh_token'])
        
        if token:
            for t in ["receivables", "payables"]:
                end = f"https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/{'contas-a-receber' if t=='receivables' else 'contas-a-pagar'}/buscar"
                params = {"data_vencimento_de": d_ini.strftime('%Y-%m-%d'), "data_vencimento_ate": d_fim.strftime('%Y-%m-%d')}
                res = requests.get(end, headers={"Authorization": f"Bearer {token}"}, params=params).json()
                
                for i in res.get("itens", []):
                    val = i.get('valor') or i.get('valor_total') or 0
                    dt = pd.to_datetime(i.get('data_vencimento')).strftime('%d/%m/%Y')
                    data_points.append({'Data': dt, 'Empresa': emp, 'Tipo': 'Receita' if t=='receivables' else 'Despesa', 'Valor': float(val) * (1 if t=='receivables' else -1)})
    
    if data_points:
        df = pd.DataFrame(data_points)
        c1, c2, c3 = st.columns(3)
        rec = df[df['Valor'] > 0]['Valor'].sum()
        des = abs(df[df['Valor'] < 0]['Valor'].sum())
        c1.metric("Entradas", f"R$ {rec:,.2f}")
        c2.metric("Saídas", f"R$ {des:,.2f}")
        c3.metric("Saldo", f"R$ {(rec-des):,.2f}")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.error("Nenhum dado encontrado ou Falha de Token. Reconecte a empresa no modo ADM.")
