import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go
import time

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        .floating-theme {{ position: fixed; top: 10px; right: 15px; z-index: 999999; }}
        .floating-theme button {{ background: transparent !important; border: 1px solid #888 !important; border-radius: 5px; }}
        .debug-container {{ border: 2px solid #ff4b4b; padding: 15px; border-radius: 10px; margin-bottom: 20px; background-color: rgba(255, 75, 75, 0.05); }}
        .spacer {{ height: 80vh; }}
    </style>
    """, unsafe_allow_html=True)

st.markdown('<div class="floating-theme">', unsafe_allow_html=True)
if st.button("🌓", key="theme_toggle"):
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

def update_token_sheet(empresa, rt):
    sh = get_sheet()
    try:
        cell = sh.find(empresa)
        sh.update_cell(cell.row, 2, rt)
    except:
        sh.append_row([empresa, rt])

def get_new_access_token(empresa):
    sh = get_sheet()
    try:
        cell = sh.find(empresa)
        rt_atual = sh.cell(cell.row, 2).value
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
                            headers={"Authorization": f"Basic {B64_AUTH}"}, 
                            data={"grant_type": "refresh_token", "refresh_token": rt_atual})
        if res.status_code == 200:
            data = res.json()
            update_token_sheet(empresa, data['refresh_token'])
            return data['access_token']
        return None
    except:
        return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.title("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas_list = df_db['empresa'].unique().tolist()
    except:
        empresas_list = []
        
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas_list)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown('<div class="spacer"></div>', unsafe_allow_html=True)
    if st.button("👁️", key="adm_eye"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

# --- 4. ÁREA ADMINISTRATIVA ---
st.title("📊 Fluxo de Caixa BPO")

if st.session_state.adm_mode:
    with st.container(border=True):
        st.subheader("🔑 Área do Administrador")
        senha = st.text_input("Senha de Acesso", type="password")
        if senha == "8429coconoiaKc#":
            st.success("Acesso Liberado")
            st.link_button("🔌 Conectar/Reconectar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")
            
            # Captura de retorno da conexão
            if "code" in st.query_params:
                st.divider()
                st.warning("Nova conexão detectada!")
                nome_nova = st.text_input("Nome da Empresa que acabou de logar:")
                if st.button("Salvar Nova Conexão"):
                    r = requests.post("https://auth.contaazul.com/oauth2/token", headers={"Authorization": f"Basic {B64_AUTH}"},
                                      data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
                    if r.status_code == 200:
                        update_token_sheet(nome_nova, r.json()['refresh_token'])
                        st.success("Salvo! Limpando URL...")
                        time.sleep(1)
                        st.query_params.clear()
                        st.rerun()

# --- 5. CONSULTA ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    st.markdown('<div class="debug-container">', unsafe_allow_html=True)
    st.subheader("🛠️ Log de Depuração")
    
    for emp in lista_alvo:
        st.write(f"**Empresa:** {emp}")
        token = get_new_access_token(emp)
        
        if not token:
            st.error(f"❌ Falha ao renovar Token para {emp}. O Refresh Token pode ter expirado. Por favor, reconecte a empresa no modo ADM.")
            continue

        headers = {"Authorization": f"Bearer {token}", "Cache-Control": "no-cache"}
        url = "https://api.contaazul.com/v1/financeiro/lancamentos"
        params = {"data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'), "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')}
        
        res = requests.get(url, headers=headers, params=params)
        
        if res.status_code == 200:
            itens = res.json()
            st.write(f"✅ {len(itens)} lançamentos obtidos.")
            for lanc in itens:
                if isinstance(lanc, dict):
                    data_points.append({
                        'Data': pd.to_datetime(lanc.get('data_vencimento')).date(),
                        'Tipo': 'Recebimentos' if lanc.get('tipo') == 'RECEBER' else 'Pagamentos',
                        'Valor': float(lanc.get('valor', 0))
                    })
        else:
            st.error(f"❌ Erro {res.status_code} na API. Verifique as permissões do App.")

    st.markdown('</div>', unsafe_allow_html=True)

    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Recebimentos', 'Pagamentos']:
            if col not in df_daily: df_daily[col] = 0
        
        df_daily = df_daily.sort_values('Data')
        df_daily['Saldo_Acumulado'] = (df_daily['Recebimentos'] - df_daily['Pagamentos']).cumsum()
        
        # Dashboard Visual
        c1, c2, c3 = st.columns(3)
        c1.metric("A Receber", f"R$ {df_daily['Recebimentos'].sum():,.2f}")
        c2.metric("A Pagar", f"R$ {df_daily['Pagamentos'].sum():,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(df_daily['Recebimentos'].sum() - df_daily['Pagamentos'].sum()):,.2f}")

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data'], y=df_daily['Recebimentos'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data'], y=df_daily['Pagamentos'], name='Pagar', marker_color='#EF553B'))
        fig.update_layout(template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white", barmode='group')
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_daily, use_container_width=True, hide_index=True)
