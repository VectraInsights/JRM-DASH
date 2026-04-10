import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go
import time

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

IS_DARK    = st.session_state.theme == 'dark'
BG_COLOR   = "#0e1117"  if IS_DARK else "#ffffff"
TEXT_COLOR = "#ffffff"   if IS_DARK else "#31333F"
INPUT_BG   = "#262730"   if IS_DARK else "#f0f2f6"
BORDER     = "#555"      if IS_DARK else "#ccc"
PLOTLY_TPL = "plotly_dark" if IS_DARK else "plotly_white"

# --- 2. CSS + CALENDÁRIO PT-BR ---
st.markdown(f"""
<style>
    header {{visibility: hidden;}}
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_COLOR}; }}
    section[data-testid="stSidebar"] {{ background-color: {"#16181f" if IS_DARK else "#f8f9fb"} !important; }}
    
    /* Fix para o Date Input e Popover */
    div[data-testid="stDateInput"] > div {{ background: transparent !important; }}
    div[data-testid="stDateInput"] input {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
        border-radius: 8px !important;
    }}
    div[data-baseweb="popover"] {{ border-radius: 10px !important; }}
    
    #theme-btn button {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 8px !important;
    }}
</style>

<script>
const EN_PT = {{'January':'Janeiro','February':'Fevereiro','March':'Março','April':'Abril','May':'Maio','June':'Junho',
                'July':'Julho','August':'Agosto','September':'Setembro','October':'Outubro','November':'Novembro','December':'Dezembro',
                'Su':'Dom','Mo':'Seg','Tu':'Ter','We':'Qua','Th':'Qui','Fr':'Sex','Sa':'Sáb'}};
function traduzir(el) {{
    if (!el) return;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {{
        const t = node.nodeValue.trim();
        if (EN_PT[t]) node.nodeValue = node.nodeValue.replace(t, EN_PT[t]);
    }}
}}
const obs = new MutationObserver(muts => {{
    muts.forEach(m => m.addedNodes.forEach(n => {{
        if (n.nodeType === 1 && n.querySelector('[data-baseweb="calendar"]')) traduzir(n);
    }}));
}});
obs.observe(document.body, {{ childList: true, subtree: true }});
</script>
""", unsafe_allow_html=True)

# --- 3. TÍTULO + BOTÃO TEMA ---
col_titulo, col_tema = st.columns([11, 1])
with col_titulo:
    st.title("📊 Fluxo de Caixa BPO")
with col_tema:
    st.markdown('<div id="theme-btn">', unsafe_allow_html=True)
    if st.button("🌓", key="toggle_theme"):
        st.session_state.theme = 'light' if IS_DARK else 'dark'
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- 4. CREDENCIAIS ---
CLIENT_ID     = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI  = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL  = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
B64_AUTH      = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
TOKEN_URL      = "https://auth.contaazul.com/oauth2/token"

# --- 5. FUNÇÕES DE SUPORTE ---
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
    try:
        sh = get_sheet()
        cell = sh.find(empresa_nome)
        if not cell: return None
        rt = sh.cell(cell.row, 2).value
        
        res = requests.post(TOKEN_URL, 
                            headers={"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"},
                            data={"grant_type": "refresh_token", "refresh_token": rt})
        
        # DEBUG TOKEN
        with st.expander(f"🔍 Debug Token — {empresa_nome}"):
            st.write("Status:", res.status_code)
            st.json(res.json())

        if res.status_code == 200:
            token_data = res.json()
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
    except Exception as e:
        st.error(f"Erro token {empresa_nome}: {e}")
    return None

# --- 6. BARRA LATERAL ---
with st.sidebar:
    st.title("Filtros")
    lista_empresas = listar_empresas()
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim    = st.date_input("Fim", datetime.now() + timedelta(days=30), format="DD/MM/YYYY")
    st.divider()
    modo_adm = st.checkbox("Modo Gestão", key="adm_check")

# --- 7. PAINEL ADM ---
params = st.query_params.to_dict()
if modo_adm or "code" in params:
    with st.container(border=True):
        st.subheader("🔐 Gestão de Empresas")
        if "code" in params:
            nome_nova = st.text_input("Nome da empresa:")
            if st.button("Gravar na Planilha"):
                resp = requests.post(TOKEN_URL, headers={"Authorization": f"Basic {B64_AUTH}"},
                                    data={"grant_type": "authorization_code", "code": params["code"], "redirect_uri": REDIRECT_URI})
                if resp.status_code == 200:
                    get_sheet().append_row([nome_nova, resp.json()['refresh_token']])
                    st.success("Salvo!")
                    st.query_params.clear()
                    st.rerun()
        else:
            pwd = st.text_input("Senha Master", type="password")
            if pwd == "8429coconoiaKc#":
                url_ca = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
                st.link_button("🔌 Conectar Nova Empresa", url_ca)

# --- 8. CONSULTA PRINCIPAL ---
if st.button("🚀 Consultar Fluxo de Caixa", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    all_data = []

    with st.spinner("Buscando dados..."):
        for emp in alvos:
            tk = get_access_token(emp)
            if not tk: continue

            for tipo, endpoint in [("Receber", "https://api.contaazul.com/v1/receivables"), 
                                   ("Pagar", "https://api.contaazul.com/v1/payables")]:
                res = requests.get(endpoint, headers={"Authorization": f"Bearer {tk}"},
                                   params={"emission_start": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                                           "emission_end": d_fim.strftime('%Y-%m-%dT23:59:59Z')})
                
                # DEBUG API
                with st.expander(f"🔍 Debug API — {emp} / {tipo}"):
                    st.write("Status:", res.status_code)
                    try: st.json(res.json())
                    except: st.write(res.text)

                if res.status_code == 200:
                    items = res.json().get('items', []) if isinstance(res.json(), dict) else res.json()
                    for l in items:
                        all_data.append({
                            'Empresa': emp,
                            'Data': pd.to_datetime(l.get('due_date', l.get('emission'))[:10]),
                            'Tipo': tipo,
                            'Valor': float(l.get('value', 0))
                        })

    if all_data:
        df = pd.DataFrame(all_data)
        # Resumo e Gráficos
        df_resumo = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Receber', 'Pagar']: 
            if col not in df_resumo.columns: df_resumo[col] = 0.0
        
        df_resumo['Saldo'] = df_resumo['Receber'] - df_resumo['Pagar']
        df_resumo['Acumulado'] = df_resumo['Saldo'].cumsum()

        # Métricas
        c1, c2, c3 = st.columns(3)
        c1.metric("A Receber", f"R$ {df['Valor'][df['Tipo']=='Receber'].sum():,.2f}")
        c2.metric("A Pagar", f"R$ {df['Valor'][df['Tipo']=='Pagar'].sum():,.2f}")
        c3.metric("Saldo", f"R$ {df_resumo['Saldo'].sum():,.2f}")

        # Plotly
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=df_resumo['Receber'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=-df_resumo['Pagar'], name='Pagar', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_resumo['Data'], y=df_resumo['Acumulado'], name='Saldo Acumulado'))
        fig.update_layout(template=PLOTLY_TPL, barmode='relative')
        st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(df_resumo, use_container_width=True)
    else:
        st.info("Nenhum dado encontrado.")
