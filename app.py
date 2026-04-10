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

# Inicialização de estados
if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

# Definição de cores dinâmicas
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "white" if st.session_state.theme == 'dark' else "#31333F"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        [data-testid="stSidebar"] {{ background-color: {side_bg} !important; }}
        [data-testid="stSidebar"] * {{ color: {txt} !important; }}
        [data-testid="stSidebar"] button {{
            border: none !important; background: transparent !important;
            padding: 0 !important; width: auto !important;
            box-shadow: none !important; font-size: 18px !important;
        }}
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

# --- 3. SIDEBAR ---
with st.sidebar:
    st.subheader("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    except:
        empresas = []
        st.error("Erro ao carregar planilha.")

    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15), format="DD/MM/YYYY")
    
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.divider()
    c1, c2, _ = st.columns([0.2, 0.2, 0.6])
    with c1:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️", key="btn_adm"):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with c2:
        if st.button("🌓", key="btn_theme"):
            st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
            st.rerun()

# --- 4. ÁREA ADM ---
if st.session_state.adm_mode:
    with st.expander("🔐 Área Administrativa", expanded=True):
        pwd = st.text_input("Senha", type="password")
        if pwd == "8429coconoiaKc#":
            st.success("Acesso Liberado")
            st.link_button("🔗 Conectar Nova Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")
            
            # Opção de renomear rápida (conforme pedido antes)
            st.divider()
            st.write("Renomear existente:")
            col_a, col_b = st.columns(2)
            target = col_a.selectbox("De:", empresas, key="rename_old")
            new_name = col_b.text_input("Para:", key="rename_new")
            if st.button("Salvar Novo Nome"):
                sh = get_sheet()
                cell = sh.find(target)
                sh.update_cell(cell.row, 1, new_name)
                st.rerun()

# --- 5. CONSULTA E GRÁFICOS ---
st.title("📊 Fluxo de Caixa BPO")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_proc = empresas if selecao == "TODAS" else [selecao]
    
    with st.spinner('Buscando dados na Conta Azul...'):
        for emp in lista_proc:
            row = df_db[df_db['empresa'] == emp].iloc[0]
            token = refresh_access_token(row['refresh_token'])
            
            if token:
                for t in ["receivables", "payables"]:
                    slug = 'contas-a-receber' if t=='receivables' else 'contas-a-pagar'
                    url = f"https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/{slug}/buscar"
                    params = {
                        "data_vencimento_de": d_ini.strftime('%Y-%m-%d'), 
                        "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'),
                        "tamanho_pagina": 500 
                    }
                    res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params).json()
                    
                    for i in res.get("itens", []):
                        v = (i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 0.0)
                        dt = i.get('data_vencimento') or i.get('due_date')
                        data_points.append({
                            'Data': pd.to_datetime(dt),
                            'Tipo': 'Recebimentos' if t=='receivables' else 'Pagamentos',
                            'Valor': float(v)
                        })

    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        
        if 'Recebimentos' not in df_daily: df_daily['Recebimentos'] = 0
        if 'Pagamentos' not in df_daily: df_daily['Pagamentos'] = 0
        
        df_daily = df_daily.sort_values('Data')
        df_daily['Saldo_Dia'] = df_daily['Recebimentos'] - df_daily['Pagamentos']
        df_daily['Saldo_Acumulado'] = df_daily['Saldo_Dia'].cumsum()
        df_daily['Data_Str'] = df_daily['Data'].dt.strftime('%d %b')

        # --- GRÁFICO ---
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data_Str'], y=df_daily['Recebimentos'], name='Recebimentos', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data_Str'], y=-df_daily['Pagamentos'], name='Pagamentos', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data_Str'], y=df_daily['Saldo_Acumulado'], name='Saldo', 
                                 line=dict(color='#34495e', width=3), mode='lines+markers'))

        fig.update_layout(
            barmode='relative', 
            template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
            legend=dict(orientation="h", y=-0.2),
            height=450, margin=dict(l=10, r=10, t=30, b=10)
        )
        st.plotly_chart(fig, use_container_width=True)

        # Métricas
        m1, m2, m3 = st.columns(3)
        m1.metric("Entradas", f"R$ {df_daily['Recebimentos'].sum():,.2f}")
        m2.metric("Saídas", f"R$ {df_daily['Pagamentos'].sum():,.2f}")
        m3.metric("Saldo", f"R$ {df_daily['Saldo_Dia'].sum():,.2f}")
        
        st.dataframe(df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Saldo_Acumulado']], use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum dado encontrado para este filtro.")
