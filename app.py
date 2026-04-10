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
PLOTLY_TPL = "plotly_dark" if IS_DARK else "plotly_white"

# --- 2. CREDENCIAIS ---
CLIENT_ID     = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI  = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL  = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
SCOPE         = "openid+profile+aws.cognito.signin.user.admin"
API_BASE_URL   = "https://api-v2.contaazul.com"
TOKEN_URL      = "https://auth.contaazul.com/oauth2/token"
B64_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

# --- 3. FUNÇÕES DE SUPORTE ---
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
        
        res = requests.post(
            TOKEN_URL, 
            headers={"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt}
        )

        if res.status_code == 200:
            token_data = res.json()
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
    except Exception as e:
        st.error(f"Erro ao obter token: {e}")
    return None

# --- 4. INTERFACE ---
col_t, col_btn = st.columns([10, 2])
with col_t: st.title("📊 Fluxo de Caixa BPO")
with col_btn:
    if st.button("🌓 Tema"):
        st.session_state.theme = 'light' if IS_DARK else 'dark'
        st.rerun()

with st.sidebar:
    st.header("Filtros")
    empresas = listar_empresas()
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_inicio = st.date_input("Início", datetime.now() - timedelta(days=7))
    d_fim    = st.date_input("Fim", datetime.now() + timedelta(days=30))
    st.divider()
    debug_mode = st.checkbox("🔍 Mostrar Logs de Depuração")
    modo_adm = st.checkbox("⚙️ Modo Gestão")

# --- 5. LÓGICA DE CONSULTA ---
if st.button("🚀 Consultar Fluxo de Caixa", type="primary"):
    alvos = empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados_brutos = []
    logs = []

    with st.spinner("Sincronizando..."):
        for emp in alvos:
            token = get_access_token(emp)
            if not token: 
                logs.append(f"❌ {emp}: Falha ao obter Token.")
                continue

            endpoints = [
                ("Receber", f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber"),
                ("Pagar", f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar")
            ]

            for tipo, url in endpoints:
                p = {"due_after": d_inicio.strftime('%Y-%m-%d'), "due_before": d_fim.strftime('%Y-%m-%d')}
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=p)
                
                # Armazenar log da requisição
                logs.append({
                    "Empresa": emp,
                    "Tipo": tipo,
                    "Status": res.status_code,
                    "URL": res.url,
                    "Resposta": res.text[:200] + "..." if len(res.text) > 200 else res.text
                })

                if res.status_code == 200:
                    for item in res.json():
                        dt_iso = item.get('due_date', item.get('emission'))[:10]
                        dados_brutos.append({
                            'Empresa': emp,
                            'Data_Sort': pd.to_datetime(dt_iso),
                            'Data': pd.to_datetime(dt_iso).strftime('%d/%m/%Y'),
                            'Tipo': tipo,
                            'Valor': float(item.get('value', 0)),
                            'Descrição': item.get('description', 'S/D')
                        })

    # --- EXIBIÇÃO ---
    if dados_brutos:
        df = pd.DataFrame(dados_brutos)
        c1, c2, c3 = st.columns(3)
        rec = df[df['Tipo'] == 'Receber']['Valor'].sum()
        pag = df[df['Tipo'] == 'Pagar']['Valor'].sum()
        c1.metric("A Receber", f"R$ {rec:,.2f}")
        c2.metric("A Pagar", f"R$ {pag:,.2f}")
        c3.metric("Saldo", f"R$ {(rec-pag):,.2f}")

        # Gráfico
        df_p = df.groupby(['Data_Sort', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index().sort_values('Data_Sort')
        fig = go.Figure()
        if 'Receber' in df_p.columns: fig.add_trace(go.Bar(x=df_p['Data_Sort'], y=df_p['Receber'], name='Receber', marker_color='#00CC96'))
        if 'Pagar' in df_p.columns: fig.add_trace(go.Bar(x=df_p['Data_Sort'], y=-df_p['Pagar'], name='Pagar', marker_color='#EF553B'))
        st.plotly_chart(fig, use_container_width=True)
        
        st.dataframe(df[['Data', 'Empresa', 'Tipo', 'Descrição', 'Valor']].sort_values('Data_Sort', ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum lançamento encontrado.")

    # Seção de Depuração
    if debug_mode or not dados_brutos:
        with st.expander("🛠️ Logs Técnicos de Depuração", expanded=not dados_brutos):
            for l in logs:
                st.write(l)

# --- 6. MODO GESTÃO (OAUTH) ---
if modo_adm:
    # Lógica de conexão omitida por brevidade, mas mantida conforme sua versão anterior
    st.info("Use esta seção para conectar novas empresas via OAuth.")
