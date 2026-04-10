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

# Cores dinâmicas para elementos fixos
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        
        /* Botão de Tema no Topo Direito */
        .floating-theme {{
            position: fixed;
            top: 10px;
            right: 15px;
            z-index: 999999;
        }}
        .floating-theme button {{
            background: transparent !important;
            border: 1px solid #888 !important;
            border-radius: 5px;
            font-size: 14px !important;
        }}

        /* Container de Debug com Contorno */
        .debug-container {{
            border: 2px solid #ff4b4b;
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            background-color: rgba(255, 75, 75, 0.05);
        }}
        
        /* Espaçador para o olho */
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

def refresh_access_token(rt, empresa):
    url = "https://auth.contaazul.com/oauth2/token"
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, 
                        data={"grant_type": "refresh_token", "refresh_token": rt})
    if res.status_code == 200:
        data = res.json()
        update_token_sheet(empresa, data['refresh_token'])
        return data['access_token']
    return None

# --- 3. SIDEBAR ---
with st.sidebar:
    st.title("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas_list)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown('<div class="spacer"></div>', unsafe_allow_html=True)
    if st.button("👁️", key="adm_eye"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

# --- 4. CONEXÃO & ADM ---
st.title("📊 Fluxo de Caixa BPO")

if "code" in st.query_params:
    with st.container(border=True):
        st.subheader("🔗 Nova Conexão")
        nome_empresa = st.text_input("Nome da Empresa para salvar:")
        if st.button("Confirmar Cadastro"):
            r = requests.post("https://auth.contaazul.com/oauth2/token", headers={"Authorization": f"Basic {B64_AUTH}"},
                              data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
            if r.status_code == 200:
                update_token_sheet(nome_empresa, r.json()['refresh_token'])
                st.query_params.clear()
                st.rerun()

if st.session_state.adm_mode:
    with st.expander("🔑 Configurações ADM"):
        if st.text_input("Senha", type="password") == "8429coconoiaKc#":
            st.link_button("🔌 Conectar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 5. EXECUÇÃO ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    # Início do Bloco de Debug com Contorno
    st.markdown('<div class="debug-container">', unsafe_allow_html=True)
    st.subheader("🛠️ Log de Depuração")
    
    for emp in lista_alvo:
        st.write(f"--- **Empresa:** {emp} ---")
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(row['refresh_token'], emp)
        
        if token:
            st.write(f"✅ Token renovado (Final: ...{token[-4:]})")
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            params = {
                "data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'),
                "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
            }
            res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            
            if res.status_code == 200:
                itens = res.json()
                st.write(f"📊 Sucesso: {len(itens)} lançamentos encontrados.")
                for lanc in itens:
                    if isinstance(lanc, dict):
                        v, tp, dt = lanc.get('valor', 0), lanc.get('tipo'), lanc.get('data_vencimento')
                        if dt and tp:
                            data_points.append({
                                'Data': pd.to_datetime(dt).date(),
                                'Tipo': 'Recebimentos' if tp == 'RECEBER' else 'Pagamentos',
                                'Valor': float(v)
                            })
            else:
                st.error(f"❌ Erro API {res.status_code}: {res.text}")
        else:
            st.error(f"❌ Falha crítica ao renovar token de {emp}.")
    
    st.markdown('</div>', unsafe_allow_html=True)

    # --- EXIBIÇÃO ---
    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Recebimentos', 'Pagamentos']:
            if col not in df_daily: df_daily[col] = 0
        
        df_daily = df_daily.sort_values('Data')
        df_daily['Saldo_Acumulado'] = (df_daily['Recebimentos'] - df_daily['Pagamentos']).cumsum()
        df_daily['Data_Grafico'] = df_daily['Data'].apply(lambda x: x.strftime('%d/%m'))

        c1, c2, c3 = st.columns(3)
        c1.metric("A Receber", f"R$ {df_daily['Recebimentos'].sum():,.2f}")
        c2.metric("A Pagar", f"R$ {df_daily['Pagamentos'].sum():,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(df_daily['Recebimentos'].sum() - df_daily['Pagamentos'].sum()):,.2f}")

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=df_daily['Recebimentos'], name='Recebimentos', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=df_daily['Pagamentos'], name='Pagamentos', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data_Grafico'], y=df_daily['Saldo_Acumulado'], name='Saldo', line=dict(color='#34495e', width=4)))
        
        fig.update_layout(barmode='group', template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
                          legend=dict(orientation="h", y=-0.2), height=500)
        st.plotly_chart(fig, use_container_width=True)
        st.dataframe(df_daily, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado encontrado. Verifique o log de depuração acima.")
