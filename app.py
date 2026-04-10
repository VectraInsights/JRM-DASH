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

if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

# Estilização
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        .floating-theme {{ position: fixed; top: 10px; right: 15px; z-index: 999999; }}
        .floating-theme button {{ background: transparent !important; border: 1px solid #888 !important; border-radius: 5px; }}
        .debug-container {{ border: 2px solid #ff4b4b; padding: 15px; border-radius: 10px; margin-top: 10px; background-color: rgba(255, 75, 75, 0.05); }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. INTEGRAÇÕES ---
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
            sh.update_cell(cell.row, 2, data['refresh_token'])
            return data['access_token']
        return None
    except:
        return None

# --- 3. BARRA LATERAL ---
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
    
    st.markdown('<div style="height: 60vh;"></div>', unsafe_allow_html=True)
    if st.button("🌓 Tema"):
        st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
        st.rerun()
    if st.button("👁️ ADM"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

# --- 4. ÁREA ADMINISTRATIVA ---
st.title("📊 Fluxo de Caixa BPO")

if st.session_state.adm_mode:
    with st.container(border=True):
        st.subheader("🔑 Configurações")
        if st.text_input("Senha", type="password") == "8429coconoiaKc#":
            st.link_button("🔌 Reconectar Conta Azul", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")
            
            if "code" in st.query_params:
                nome_fina = st.text_input("Confirmar nome da empresa:")
                if st.button("Salvar Novo Token"):
                    r = requests.post("https://auth.contaazul.com/oauth2/token", headers={"Authorization": f"Basic {B64_AUTH}"},
                                      data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
                    if r.status_code == 200:
                        update_token_sheet(nome_fina, r.json()['refresh_token'])
                        st.success("Conectado com sucesso!")
                        st.query_params.clear()
                        st.rerun()

# --- 5. CONSULTA E LOG AVANÇADO ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    with st.expander("🛠️ Log de Depuração Avançado", expanded=True):
        st.markdown('<div class="debug-container">', unsafe_allow_html=True)
        for emp in lista_alvo:
            st.write(f"🔍 Verificando: **{emp}**")
            token = get_new_access_token(emp)
            
            if not token:
                st.error(f"❌ Falha crítica ao gerar Access Token para {emp}. O Refresh Token na planilha é inválido.")
                continue

            # Chamada da API
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            params = {
                "data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'), 
                "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
            }
            res = requests.get("https://api.contaazul.com/v1/financeiro/lancamentos", headers=headers, params=params)
            
            if res.status_code == 200:
                itens = res.json()
                st.success(f"✅ {len(itens)} lançamentos brutos recebidos.")
                for l in itens:
                    data_points.append({
                        'Data': pd.to_datetime(l.get('data_vencimento')).date(),
                        'Tipo': 'Receber' if l.get('tipo') == 'RECEBER' else 'Pagar',
                        'Valor': float(l.get('valor', 0))
                    })
            else:
                st.error(f"❌ Erro {res.status_code} retornado pela Conta Azul")
                st.write("Detalhes do erro que a API enviou:")
                try:
                    st.json(res.json())
                except:
                    st.write(res.text)
        st.markdown('</div>', unsafe_allow_html=True)

    # Gráficos e Tabela (apenas se houver dados)
    if data_points:
        df = pd.DataFrame(data_points)
        df_resumo = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for c in ['Receber', 'Pagar']: 
            if c not in df_resumo: df_resumo[c] = 0
            
        st.subheader("Resultado do Período")
        st.dataframe(df_resumo.sort_values('Data'), use_container_width=True, hide_index=True)
        
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=df_resumo['Receber'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_resumo['Data'], y=df_resumo['Pagar'], name='Pagar', marker_color='#EF553B'))
        fig.update_layout(template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white", barmode='group')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("A consulta não retornou dados financeiros para o período selecionado.")
