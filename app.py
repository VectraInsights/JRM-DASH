import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

IS_DARK    = st.session_state.theme == 'dark'
BG_COLOR   = "#0e1117"  if IS_DARK else "#ffffff"
TEXT_COLOR = "#ffffff"   if IS_DARK else "#31333F"
INPUT_BG   = "#262730"   if IS_DARK else "#f0f2f6"
BORDER     = "#555"      if IS_DARK else "#ccc"
PLOTLY_TPL = "plotly_dark" if IS_DARK else "plotly_white"

# --- 2. CREDENCIAIS E ENDPOINTS (ATUALIZADOS V2) ---
CLIENT_ID     = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI  = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL  = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"

# Escopo obrigatório para contas novas/migradas
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

# URLs Oficiais de Autenticação e API
AUTH_LOGIN_URL = "https://auth.contaazul.com/login"
TOKEN_URL      = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL   = "https://api-v2.contaazul.com"

# Encode Base64 para o Header de Autenticação
B64_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

# --- 3. CSS CUSTOMIZADO ---
st.markdown(f"""
<style>
    header {{visibility: hidden;}}
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_COLOR}; }}
    section[data-testid="stSidebar"] {{ background-color: {"#16181f" if IS_DARK else "#f8f9fb"} !important; }}
    div[data-testid="stMetricValue"] {{ font-size: 1.8rem !important; }}
</style>
""", unsafe_allow_html=True)

# --- 4. FUNÇÕES DE SUPORTE ---
def get_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

def listar_empresas():
    try:
        df = pd.DataFrame(get_sheet().get_all_records())
        return df['empresa'].dropna().unique().tolist() if not df.empty else []
    except: return []

def get_access_token(empresa_nome):
    """Realiza o Refresh do Token com Basic Auth e atualiza a planilha"""
    try:
        sh = get_sheet()
        cell = sh.find(empresa_nome)
        if not cell: return None
        rt = sh.cell(cell.row, 2).value
        
        res = requests.post(
            TOKEN_URL, 
            headers={
                "Authorization": f"Basic {B64_AUTH}", 
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={"grant_type": "refresh_token", "refresh_token": rt}
        )

        if res.status_code == 200:
            token_data = res.json()
            # A Conta Azul pode rotacionar o Refresh Token; salvamos o novo
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
        else:
            st.error(f"Erro de Autenticação ({empresa_nome}): {res.status_code}")
    except Exception as e:
        st.error(f"Falha técnica ao obter token: {e}")
    return None

# --- 5. TÍTULO E BOTÃO DE TEMA ---
col_t, col_btn = st.columns([10, 2])
with col_t:
    st.title("📊 Fluxo de Caixa BPO")
with col_btn:
    if st.button("🌓 Alterar Tema"):
        st.session_state.theme = 'light' if IS_DARK else 'dark'
        st.rerun()

# --- 6. BARRA LATERAL (FILTROS) ---
with st.sidebar:
    st.header("Configurações")
    empresas_disponiveis = listar_empresas()
    sel_empresa = st.selectbox("Selecione a Empresa", ["TODAS"] + empresas_disponiveis)
    
    d_inicio = st.date_input("Data Inicial", datetime.now() - timedelta(days=7))
    d_fim    = st.date_input("Data Final", datetime.now() + timedelta(days=30))
    
    st.divider()
    modo_adm = st.checkbox("Modo Gestão (Conexão)")

# --- 7. PAINEL DE GESTÃO (OAUTH FLOW) ---
params = st.query_params.to_dict()
if modo_adm or "code" in params:
    with st.expander("🔐 Configuração de Nova Empresa", expanded=True):
        if "code" in params:
            nome_nova = st.text_input("Nome da Empresa para salvar:")
            if st.button("Confirmar Conexão"):
                resp = requests.post(
                    TOKEN_URL, 
                    headers={"Authorization": f"Basic {B64_AUTH}"},
                    data={
                        "grant_type": "authorization_code", 
                        "code": params["code"], 
                        "redirect_uri": REDIRECT_URI
                    }
                )
                if resp.status_code == 200:
                    get_sheet().append_row([nome_nova, resp.json()['refresh_token']])
                    st.success(f"Empresa '{nome_nova}' conectada!")
                    st.query_params.clear()
                    st.rerun()
        else:
            pwd = st.text_input("Senha Master", type="password")
            if pwd == "8429coconoiaKc#":
                url_auth = f"{AUTH_LOGIN_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
                st.link_button("🔌 Conectar com Conta Azul", url_auth)

# --- 8. PROCESSAMENTO E EXIBIÇÃO ---
if st.button("🚀 Consultar Fluxo de Caixa", type="primary"):
    alvos = empresas_disponiveis if sel_empresa == "TODAS" else [sel_empresa]
    dados_brutos = []

    with st.spinner("Sincronizando com a Conta Azul..."):
        for emp in alvos:
            token = get_access_token(emp)
            if not token: continue

            # Endpoints Financeiros V2
            endpoints = [
                ("Receber", f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber"),
                ("Pagar", f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar")
            ]

            for tipo, url in endpoints:
                # O filtro na API exige AAAA-MM-DD
                res = requests.get(
                    url, 
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "due_after": d_inicio.strftime('%Y-%m-%d'),
                        "due_before": d_fim.strftime('%Y-%m-%d')
                    }
                )
                
                if res.status_code == 200:
                    for item in res.json():
                        dt_original = item.get('due_date')[:10]
                        dados_brutos.append({
                            'Empresa': emp,
                            'Data_Sort': pd.to_datetime(dt_original), # Para ordenação do gráfico
                            'Data': pd.to_datetime(dt_original).strftime('%d/%m/%Y'), # Para o usuário
                            'Tipo': tipo,
                            'Valor': float(item.get('value', 0)),
                            'Descrição': item.get('description', 'Sem descrição')
                        })

    if dados_brutos:
        df = pd.DataFrame(dados_brutos)
        
        # Resumo Financeiro
        total_rec = df[df['Tipo'] == 'Receber']['Valor'].sum()
        total_pag = df[df['Tipo'] == 'Pagar']['Valor'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("A Receber", f"R$ {total_rec:,.2f}")
        c2.metric("A Pagar", f"R$ {total_pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo", f"R$ {(total_rec - total_pag):,.2f}")

        # Preparação do Gráfico (Usando Data_Sort para ordem correta)
        df_plot = df.groupby(['Data_Sort', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        df_plot = df_plot.sort_values('Data_Sort')
        
        fig = go.Figure()
        if 'Receber' in df_plot.columns:
            fig.add_trace(go.Bar(x=df_plot['Data_Sort'], y=df_plot['Receber'], name='Receber', marker_color='#00CC96'))
        if 'Pagar' in df_plot.columns:
            fig.add_trace(go.Bar(x=df_plot['Data_Sort'], y=-df_plot['Pagar'], name='Pagar', marker_color='#EF553B'))
            
        fig.update_layout(
            template=PLOTLY_TPL, 
            barmode='relative',
            xaxis_title="Vencimento",
            yaxis_title="Valor (R$)",
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tabela Final formatada
        st.subheader("Detalhamento dos Lançamentos")
        st.dataframe(
            df[['Data', 'Empresa', 'Tipo', 'Descrição', 'Valor']].sort_values('Data'),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Nenhum lançamento encontrado para os filtros selecionados.")
