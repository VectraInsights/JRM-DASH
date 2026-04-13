import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="Fluxo de Caixa JRM", layout="wide", initial_sidebar_state="collapsed")

# (Estilos CSS mantidos...)
st.markdown("""
    <style>
        .block-container {padding-top: 1rem !important;}
        div[data-testid="stMetric"] {
            background: rgba(128, 128, 128, 0.05); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 15px; border-radius: 10px;
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO (INTEGRAÇÃO E TOKEN) ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = dict(st.secrets["google_sheets"])
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        return gspread.authorize(creds).open_by_url("SUA_URL_DA_PLANILHA").sheet1
    except: return None

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        auth_b64 = base64.b64encode(f"{st.secrets['conta_azul']['client_id']}:{st.secrets['conta_azul']['client_secret']}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
        return None
    except: return None

def buscar_dados_v2(endpoint, headers, params):
    todos_itens = []
    params["status"] = "EM_ABERTO"
    params["tamanho_pagina"] = 100
    pagina = 1
    while True:
        params["pagina"] = pagina
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        itens = res.json().get('itens', [])
        if not itens: break
        for item in itens:
            total, pago = item.get('total', 0), item.get('pago', 0)
            if (total - pago) > 0:
                todos_itens.append({"Vencimento": item.get("data_vencimento"), "Valor": total - pago})
        if len(itens) < 100: break
        pagina += 1
    return todos_itens

# --- 3. INTERFACE COM TRAVA (FORM) ---
sh = get_sheet()
clientes_base = [r[0] for r in sh.get_all_values()[1:]] if sh else []
opcoes_filtro = ["Todos os Clientes"] + clientes_base

with st.sidebar:
    # O FORM cria a trava que você precisa
    with st.form("config_form"):
        st.header("Filtros de Data")
        hoje = datetime.now().date()
        
        # Estes widgets NÃO disparam o reload agora
        data_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
        data_fim = st.date_input("Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
        empresa_selecionada = st.selectbox("Visualização", opcoes_filtro)
        
        # Único gatilho para atualizar o app
        btn_update = st.form_submit_button("Atualizar", type="primary")

st.title("Fluxo de Caixa")

# --- 4. PROCESSAMENTO (SÓ OCORRE NO CLIQUE OU CARREGAMENTO INICIAL) ---
if btn_update or "first_run" not in st.session_state:
    st.session_state.first_run = True
    empresas_focar = clientes_base if empresa_selecionada == "Todos os Clientes" else [empresa_selecionada]
    
    all_p, all_r = [], []
    
    with st.spinner(f"Consolidando dados: {empresa_selecionada}..."):
        for emp in empresas_focar:
            token = obter_token(emp)
            if token:
                headers = {"Authorization": f"Bearer {token}"}
                p = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
                all_p.extend(buscar_dados_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", headers, p))
                all_r.extend(buscar_dados_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers, p))

    if all_p or all_r:
        df_base = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
        df_base['data_str'] = df_base['data'].dt.strftime('%Y-%m-%d')
        
        val_p = pd.DataFrame(all_p).groupby('Vencimento')['Valor'].sum() if all_p else pd.Series()
        val_r = pd.DataFrame(all_r).groupby('Vencimento')['Valor'].sum() if all_r else pd.Series()
        
        df_base['Pagar'] = df_base['data_str'].map(val_p).fillna(0)
        df_base['Receber'] = df_base['data_str'].map(val_r).fillna(0)
        df_base['Saldo'] = df_base['Receber'] - df_base['Pagar']

        # Exibição de Métricas e Gráfico (Lógica de plotagem mantida...)
        c1, c2, c3 = st.columns(3)
        fmt = lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        c1.metric("A Receber", fmt(df_base['Receber'].sum()))
        c2.metric("A Pagar", fmt(df_base['Pagar'].sum()))
        c3.metric("Saldo", fmt(df_base['Saldo'].sum()))

        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_base['data'], y=df_base['Receber'], name='Receitas', marker_color='#2ecc71'))
        fig.add_trace(go.Bar(x=df_base['data'], y=df_base['Pagar'], name='Despesas', marker_color='#e74c3c'))
        fig.add_trace(go.Scatter(x=df_base['data'], y=df_base['Saldo'], name='Saldo', line=dict(color='#2C3E50', width=3)))
        
        fig.update_layout(hovermode="x unified", margin=dict(l=40, r=20, t=20, b=40), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Aguardando atualização ou nenhum dado encontrado.")
