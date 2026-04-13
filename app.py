import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES INICIAIS ---
CA_ID = st.secrets["conta_azul"]["client_id"]
CA_SECRET = st.secrets["conta_azul"]["client_secret"]
CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]
API_BASE_URL = "https://api-v2.contaazul.com" 
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
AUTH_URL = "https://auth.contaazul.com/login"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. FUNÇÕES DE BANCO DE DADOS (GOOGLE SHEETS) ---
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except: return None

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt_atual, "client_id": CA_ID, "client_secret": CA_SECRET})
        if res.status_code == 200: return res.json()['access_token']
        return None
    except: return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Configurações")
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
    url_auth = f"{AUTH_URL}?刻response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Vincular Nova Conta", url_auth, type="primary", use_container_width=True)
    
    st.divider()
    st.subheader("📅 Filtros de Busca")
    data_inicio = st.date_input("Data Inicial", datetime.now(), format="DD/MM/YYYY")
    data_fim = st.date_input("Data Final", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    sh = get_sheet()
    emp_selecionada = None
    if sh:
        try:
            dados_pl = sh.get_all_values()
            if len(dados_pl) > 1:
                df_pl = pd.DataFrame(dados_pl[1:], columns=dados_pl[0])
                emp_selecionada = st.selectbox("Selecione o Cliente Ativo", df_pl.iloc[:, 0].unique().tolist())
        except: pass

# --- 4. ÁREA PRINCIPAL ---
st.title("Painel Financeiro JRM")

if emp_selecionada:
    if st.button("🔄 Sincronizar dados", use_container_width=True):
        with st.spinner("Sincronizando..."):
            token = obter_novo_access_token(emp_selecionada)
            if token:
                headers = {"Authorization": f"Bearer {token}"}
                params = {"data_vencimento_de": data_inicio.strftime('%Y-%m-%d'), "data_vencimento_ate": data_fim.strftime('%Y-%m-%d'), "tamanho_pagina": 100}
                
                res_p = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", headers=headers, params=params)
                res_r = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers=headers, params=params)
                
                if res_p.status_code == 200 and res_r.status_code == 200:
                    # Processamento
                    df_p = pd.DataFrame(res_p.json().get('itens', []))
                    df_r = pd.DataFrame(res_r.json().get('itens', []))
                    df_plot = pd.DataFrame({'data': pd.date_range(data_inicio, data_fim)})
                    
                    for df_raw, col_name in [(df_p, 'Pagar'), (df_r, 'Receber')]:
                        if not df_raw.empty:
                            df_raw['data'] = pd.to_datetime(df_raw['data_vencimento'])
                            df_raw['valor'] = pd.to_numeric(df_raw['total'])
                            df_plot = df_plot.merge(df_raw.groupby('data')['valor'].sum(), on='data', how='left').rename(columns={'valor': col_name})
                        else: df_plot[col_name] = 0
                    
                    df_plot = df_plot.fillna(0)
                    df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

                    # --- 5. EXIBIÇÃO: CARDS NO TOPO ---
                    st.divider()
                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total Recebido", f"R$ {df_plot['Receber'].sum():,.2f}")
                    m2.metric("Total Pago", f"R$ {df_plot['Pagar'].sum():,.2f}")
                    m3.metric("Saldo do Período", f"R$ {df_plot['Saldo'].sum():,.2f}")
                    st.write("") # Espaçamento

                    # --- 6. GRÁFICO PLOTLY ---
                    fig = go.Figure()

                    fig.add_trace(go.Bar(
                        x=df_plot['data'], y=df_plot['Receber'],
                        name='Recebimentos', marker_color='#2ecc71',
                        hovertemplate='Recebimentos: R$ %{y:,.2f}<extra></extra>'
                    ))

                    fig.add_trace(go.Bar(
                        x=df_plot['data'], y=df_plot['Pagar'],
                        name='Pagamentos', marker_color='#e74c3c',
                        hovertemplate='Pagamentos: R$ %{y:,.2f}<extra></extra>'
                    ))

                    fig.add_trace(go.Scatter(
                        x=df_plot['data'], y=df_plot['Saldo'],
                        name='Saldo', line=dict(color='#34495e', width=4),
                        marker=dict(size=12, symbol='circle'),
                        hovertemplate='Saldo: R$ %{y:,.2f}<extra></extra>'
                    ))

                    fig.update_layout(
                        template="plotly_dark",
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
                        # 'closest' garante que o tooltip só apareça em cima do ponto/barra
                        hovermode="closest",
                        xaxis=dict(showgrid=False, tickformat='%d/%m', showspikes=False),
                        yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.1)', showspikes=False),
                        height=500,
                        margin=dict(l=10, r=10, t=20, b=10)
                    )

                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                else:
                    st.error("Erro ao carregar dados da API.")
