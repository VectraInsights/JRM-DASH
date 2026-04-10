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

bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "white" if st.session_state.theme == 'dark' else "black"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
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
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15), format="DD/MM/YYYY")
    
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.divider()
    c1, c2, _ = st.columns([0.15, 0.15, 0.7])
    with c1:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️"):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with c2:
        if st.button("🌓"):
            st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
            st.rerun()

# --- 4. CONSULTA E GRÁFICOS ---
st.title("📊 Fluxo de Caixa BPO")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_proc = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista_proc:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(row['refresh_token'])
        
        if token:
            for t in ["receivables", "payables"]:
                slug = 'contas-a-receber' if t=='receivables' else 'contas-a-pagar'
                url = f"https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/{slug}/buscar"
                # Aumentando tamanho da página para não perder valores
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
        
        # Garante que as colunas existam para o cálculo
        if 'Recebimentos' not in df_daily: df_daily['Recebimentos'] = 0
        if 'Pagamentos' not in df_daily: df_daily['Pagamentos'] = 0
        
        # Cálculo do Saldo Diário e Acumulado (Linha do gráfico)
        df_daily['Saldo_Dia'] = df_daily['Recebimentos'] - df_daily['Pagamentos']
        df_daily['Saldo_Acumulado'] = df_daily['Saldo_Dia'].cumsum()
        df_daily['Data_Str'] = df_daily['Data'].dt.strftime('%d %b')

        # --- CRIAÇÃO DO GRÁFICO COMBINADO (IGUAL À CONTA AZUL) ---
        fig = go.Figure()

        # Barras de Recebimentos (Verde)
        fig.add_trace(go.Bar(
            x=df_daily['Data_Str'], y=df_daily['Recebimentos'],
            name='Recebimentos', marker_color='#00CC96', offsetgroup=0
        ))

        # Barras de Pagamentos (Vermelho - Valores negativos para descer do eixo 0)
        fig.add_trace(go.Bar(
            x=df_daily['Data_Str'], y=-df_daily['Pagamentos'],
            name='Pagamentos', marker_color='#EF553B', offsetgroup=0
        ))

        # Linha de Saldo (Azul Escuro/Cinza)
        fig.add_trace(go.Scatter(
            x=df_daily['Data_Str'], y=df_daily['Saldo_Acumulado'],
            name='Saldo', line=dict(color='#34495e', width=3),
            marker=dict(size=8), mode='lines+markers'
        ))

        fig.update_layout(
            title="Fluxo de caixa diário",
            template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
            barmode='relative',
            legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
            margin=dict(l=20, r=20, t=50, b=20),
            height=500
        )

        st.plotly_chart(fig, use_container_width=True)

        # Tabela e Métricas (Mantidos)
        m1, m2, m3 = st.columns(3)
        rec_total = df_daily['Recebimentos'].sum()
        pag_total = df_daily['Pagamentos'].sum()
        m1.metric("Entradas", f"R$ {rec_total:,.2f}")
        m2.metric("Saídas", f"R$ {pag_total:,.2f}")
        m3.metric("Saldo do Período", f"R$ {(rec_total - pag_total):,.2f}")
        
        st.dataframe(df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Saldo_Acumulado']].sort_values('Data'), 
                     use_container_width=True, hide_index=True)
    else:
        st.error("Nenhum dado encontrado para o período.")
