import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "white" if st.session_state.theme == 'dark' else "#31333F"
input_fill = "#1e1e1e" if st.session_state.theme == 'dark' else "#ffffff"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        [data-testid="stSidebar"] {{ background-color: {side_bg} !important; }}
        
        /* Botão de Tema no Topo Direito */
        .theme-btn-container {{
            position: absolute; top: 10px; right: 10px; z-index: 999;
        }}
        
        /* Ajuste Sidebar */
        [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"],
        [data-testid="stSidebar"] .stDateInput div {{ background-color: {input_fill} !important; color: {txt} !important; }}
        
        /* Esconder o olho no fim da rolagem */
        .spacer {{ height: 800px; }}
        .adm-btn {{ opacity: 0.1; transition: 0.3s; }}
        .adm-btn:hover {{ opacity: 1.0; }}
    </style>
    """, unsafe_allow_html=True)

# Botão de Tema flutuante
st.markdown('<div class="theme-btn-container">', unsafe_allow_html=True)
if st.button("🌓"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- 2. API & GOOGLE SHEETS ---
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

def update_refresh_token_in_sheet(empresa_nome, new_refresh_token):
    sh = get_sheet()
    try:
        cell = sh.find(empresa_nome)
        sh.update_cell(cell.row, 2, new_refresh_token)
    except:
        pass

def get_tokens(refresh_token, empresa_nome):
    url = "https://auth.contaazul.com/oauth2/token"
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, 
                        data={"grant_type": "refresh_token", "refresh_token": refresh_token})
    if res.status_code == 200:
        data = res.json()
        # Salva o novo refresh_token para não precisar re-autenticar depois de mudar o código
        update_refresh_token_in_sheet(empresa_nome, data.get("refresh_token"))
        return data.get("access_token")
    return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    
    # Período padrão de 7 dias
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    # Empurra o "olho" para baixo (invisível sem rolar)
    st.markdown('<div class="spacer"></div>', unsafe_allow_html=True)
    st.divider()
    if st.button("👁️", help="Modo Administrador"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

# --- 4. ÁREA ADM & LOGIN ---
st.title("📊 Fluxo de Caixa BPO")

# Captura de retorno da Conta Azul
params = st.query_params
if "code" in params:
    with st.container(border=True):
        st.warning("⚠️ Nova conexão detectada. Digite o nome exato para salvar.")
        nome_nova = st.text_input("Nome da Empresa")
        if st.button("Confirmar Registro"):
            r = requests.post("https://auth.contaazul.com/oauth2/token", headers={"Authorization": f"Basic {B64_AUTH}"},
                              data={"grant_type": "authorization_code", "code": params["code"], "redirect_uri": REDIRECT_URI})
            if r.status_code == 200:
                update_refresh_token_in_sheet(nome_nova, r.json().get("refresh_token"))
                st.query_params.clear()
                st.rerun()

if st.session_state.adm_mode:
    with st.expander("🔑 Configurações", expanded=True):
        if st.text_input("Acesso", type="password") == "8429coconoiaKc#":
            st.link_button("🔌 Conectar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 5. CONSULTA ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        acc_token = get_tokens(row['refresh_token'], emp)
        
        if acc_token:
            # Consulta via Lançamentos (mais estável que eventos)
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            params_api = {
                "data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'),
                "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z'),
                "pagos": "false" # Trazer o que está previsto (aberto)
            }
            res = requests.get(url, headers={"Authorization": f"Bearer {acc_token}"}, params=params_api).json()
            
            for lanc in res:
                v = lanc.get('valor', 0)
                tp = lanc.get('tipo') # Pagar ou Receber
                dt = lanc.get('data_vencimento')
                
                data_points.append({
                    'Data': pd.to_datetime(dt).date(),
                    'Tipo': 'Recebimentos' if tp == 'RECEBER' else 'Pagamentos',
                    'Valor': float(v)
                })

    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Recebimentos', 'Pagamentos']:
            if col not in df_daily: df_daily[col] = 0
        
        df_daily = df_daily.sort_values('Data')
        df_daily['Saldo_Dia'] = df_daily['Recebimentos'] - df_daily['Pagamentos']
        df_daily['Saldo_Acumulado'] = df_daily['Saldo_Dia'].cumsum()
        df_daily['Data_Grafico'] = df_daily['Data'].apply(lambda x: x.strftime('%d/%m'))

        # Cards
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {df_daily['Recebimentos'].sum():,.2f}")
        c2.metric("Total a Pagar", f"R$ {df_daily['Pagamentos'].sum():,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(df_daily['Recebimentos'].sum() - df_daily['Pagamentos'].sum()):,.2f}")

        # Gráfico
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=df_daily['Recebimentos'], name='Recebimentos', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=df_daily['Pagamentos'], name='Pagamentos', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data_Grafico'], y=df_daily['Saldo_Acumulado'], name='Saldo Acumulado', 
                                 line=dict(color='#34495e', width=4)))
        
        fig.update_layout(barmode='group', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
                          legend=dict(orientation="h", y=-0.2), height=500)
        st.plotly_chart(fig, use_container_width=True)

        # Tabela
        df_tab = df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Saldo_Acumulado']].copy()
        df_tab['Data'] = df_tab['Data'].apply(lambda x: x.strftime('%d/%m/%Y'))
        st.dataframe(df_tab, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado encontrado. Verifique se os filtros estão corretos.")
