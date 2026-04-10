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

# --- 2. CREDENCIAIS E ENDPOINTS (ATUALIZADOS) ---
CLIENT_ID     = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI  = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL  = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"

# O "pulo do gato": Escopo obrigatório para atravessar o Cognito da AWS
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

# URLs Oficiais da Conta Azul
AUTH_LOGIN_URL = "https://auth.contaazul.com/login"
TOKEN_URL      = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL   = "https://api-v2.contaazul.com"

# Encode Base64 das credenciais para o Header Basic
B64_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

# --- 3. CSS + TRADUÇÃO ---
st.markdown(f"""
<style>
    header {{visibility: hidden;}}
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_COLOR}; }}
    section[data-testid="stSidebar"] {{ background-color: {"#16181f" if IS_DARK else "#f8f9fb"} !important; }}
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
    """Realiza o Refresh do Token usando as novas regras de autenticação"""
    try:
        sh = get_sheet()
        cell = sh.find(empresa_nome)
        if not cell: return None
        rt = sh.cell(cell.row, 2).value
        
        # Chamada de Refresh com Basic Auth
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
            # Atualiza o refresh_token na planilha (importante: ele pode mudar!)
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
        else:
            with st.expander(f"⚠️ Erro de Autenticação: {empresa_nome}"):
                st.write(f"Status {res.status_code}: {res.text}")
    except Exception as e:
        st.error(f"Erro ao processar token de {empresa_nome}: {e}")
    return None

# --- 5. INTERFACE PRINCIPAL ---
col_titulo, col_tema = st.columns([11, 1])
with col_titulo:
    st.title("📊 Fluxo de Caixa JRM Transportes")
with col_tema:
    if st.button("🌓"):
        st.session_state.theme = 'light' if IS_DARK else 'dark'
        st.rerun()

# --- 6. BARRA LATERAL ---
with st.sidebar:
    st.title("Filtros")
    lista_empresas = listar_empresas()
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("Início", datetime.now() - timedelta(days=30), format="DD/MM/YYYY")
    d_fim    = st.date_input("Fim", datetime.now() + timedelta(days=30), format="DD/MM/YYYY")
    st.divider()
    modo_adm = st.checkbox("⚙️ Modo Gestão")

# --- 7. PAINEL DE GESTÃO (CONEXÃO DE NOVAS EMPRESAS) ---
params = st.query_params.to_dict()
if modo_adm or "code" in params:
    with st.container(border=True):
        st.subheader("🔐 Gestão de Conexões")
        
        if "code" in params:
            nome_nova = st.text_input("Nome da empresa para salvar:", placeholder="Ex: JRM Transportes")
            if st.button("Gravar Nova Empresa"):
                # Troca o CODE pelo TOKEN inicial
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
                    st.success(f"Empresa '{nome_nova}' conectada com sucesso!")
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(f"Erro na troca do código: {resp.text}")
        else:
            pwd = st.text_input("Senha Master", type="password")
            if pwd == "8429coconoiaKc#":
                # URL de autorização COM O ESCOPO CORRIGIDO
                url_ca = f"{AUTH_LOGIN_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
                st.link_button("🔌 Autorizar Nova Empresa na Conta Azul", url_ca)

# --- 8. CONSULTA E GRÁFICOS ---
if st.button("🚀 Consultar Dados Financeiros", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    all_data = []

    with st.spinner("Acessando API da Conta Azul..."):
        for emp in alvos:
            tk = get_access_token(emp)
            if not tk: continue

            # Endpoints da V2 conforme documentação
            rotas = [
                ("Receber", f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber"),
                ("Pagar", f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar")
            ]

            for tipo, endpoint in rotas:
                res = requests.get(
                    endpoint, 
                    headers={"Authorization": f"Bearer {tk}"},
                    params={
                        "due_after": d_inicio.strftime('%Y-%m-01'), # Ajustado para pegar o mês cheio
                        "due_before": d_fim.strftime('%Y-%m-%d')
                    }
                )
                
                if res.status_code == 200:
                    items = res.json()
                    for l in items:
                        all_data.append({
                            'Empresa': emp,
                            'Data': pd.to_datetime(l.get('due_date')[:10]),
                            'Tipo': tipo,
                            'Valor': float(l.get('value', 0)),
                            'Status': 'Pago' if l.get('status') == 'PAID' else 'Pendente'
                        })

    if all_data:
        df = pd.DataFrame(all_data)
        
        # Cálculos de Saldo
        df_resumo = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Receber', 'Pagar']:
            if col not in df_resumo.columns: df_resumo[col] = 0.0
        
        df_resumo['Saldo Diário'] = df_resumo['Receber'] - df_resumo['Pagar']
        df_resumo['Acumulado'] = df_resumo['Saldo Diário'].cumsum()

        # KPIs
        c1, c2, c3 = st.columns(3)
        total_rec = df[df['Tipo']=='Receber']['Valor'].sum()
        total_pag = df[df['Tipo']=='Pagar']['Valor'].sum()
        c1.metric("Total a Receber", f"R$ {total_rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {total_pag:,.2f}")
        c3.metric("Saldo do Período", f"R$ {(total_rec - total_pag):,.2f}")

        # Gráfico Plotly
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=df_resumo['Receber'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=-df_resumo['Pagar'], name='Pagar', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_resumo['Data'], y=df_resumo['Acumulado'], name='Fluxo Acumulado', line=dict(color='#636EFA', width=3)))
        
        fig.update_layout(title="Projeção de Fluxo de Caixa", template=PLOTLY_TPL, barmode='relative', hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Nenhum dado financeiro encontrado para os filtros selecionados.")
