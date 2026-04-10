import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- 1. CONFIGURAÇÕES E TEMA ---
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
        [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"],
        [data-testid="stSidebar"] .stDateInput div {{ background-color: {input_fill} !important; color: {txt} !important; }}
        [data-testid="stSidebar"] p, [data-testid="stSidebar"] label {{ color: {txt} !important; }}
        [data-testid="stSidebar"] button {{ border: none !important; background: transparent !important; font-size: 22px !important; }}
    </style>
    """, unsafe_allow_html=True)

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

def refresh_access_token(refresh_token):
    url = "https://auth.contaazul.com/oauth2/token"
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data={"grant_type": "refresh_token", "refresh_token": refresh_token})
    return res.json().get("access_token") if res.status_code == 200 else None

# --- 3. CAPTURA DE NOVO ACESSO ---
params = st.query_params
if "code" in params:
    st.info("🎯 Conexão detectada! Finalize o cadastro abaixo:")
    with st.form("registro_empresa"):
        nome_emp = st.text_input("Nome da Empresa:")
        if st.form_submit_button("Salvar e Ativar"):
            res = requests.post("https://auth.contaazul.com/oauth2/token", 
                                headers={"Authorization": f"Basic {B64_AUTH}"}, 
                                data={"grant_type": "authorization_code", "code": params["code"], "redirect_uri": REDIRECT_URI})
            if res.status_code == 200:
                rt = res.json().get("refresh_token")
                sh = get_sheet()
                try:
                    cell = sh.find(nome_emp)
                    sh.update_cell(cell.row, 2, rt)
                except:
                    sh.append_row([nome_emp, rt])
                st.query_params.clear()
                st.rerun()

# --- 4. SIDEBAR ---
with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15), format="DD/MM/YYYY")
    
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

# --- 5. DASHBOARD ---
st.title("📊 Fluxo de Caixa BPO")

if st.session_state.adm_mode:
    with st.expander("🔑 Área ADM", expanded=True):
        if st.text_input("Senha", type="password") == "8429coconoiaKc#":
            st.link_button("🔗 Conectar Nova Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(row['refresh_token'])
        if token:
            for t in ["receivables", "payables"]:
                slug = 'contas-a-receber' if t=='receivables' else 'contas-a-pagar'
                url = f"https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/{slug}/buscar"
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, 
                                   params={"data_vencimento_de": d_ini.strftime('%Y-%m-%d'), 
                                           "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'),
                                           "tamanho_pagina": 1000}).json()
                
                for i in res.get("itens", []):
                    # CAPTURA AGRESSIVA DE VALOR E DATA
                    val = i.get('value') or i.get('valor') or i.get('valor_total') or i.get('total') or 0
                    dt = i.get('due_date') or i.get('data_vencimento') or i.get('data')
                    
                    if dt:
                        data_points.append({
                            'Data': pd.to_datetime(dt).date(),
                            'Tipo': 'Recebimentos' if t=='receivables' else 'Pagamentos',
                            'Valor': float(val)
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

        # --- GRÁFICO ---
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=df_daily['Recebimentos'], name='Recebimentos', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data_Grafico'], y=-df_daily['Pagamentos'], name='Pagamentos', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data_Grafico'], y=df_daily['Saldo_Acumulado'], name='Saldo', line=dict(color='#34495e', width=3), mode='lines+markers'))
        
        fig.update_layout(
            barmode='relative', 
            template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
            xaxis=dict(type='category'), # Força exibição de todas as datas como texto
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tabela Formatada (Sem horas)
        df_tab = df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Saldo_Acumulado']].copy()
        df_tab['Data'] = df_tab['Data'].apply(lambda x: x.strftime('%d/%m/%Y'))
        st.dataframe(df_tab, use_container_width=True, hide_index=True)
    else:
        st.error("Nenhum dado encontrado. Verifique se as empresas estão conectadas corretamente na Área ADM.")
