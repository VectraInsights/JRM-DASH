import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES ---
st.set_page_config(page_title="BPO Dashboard JRM", layout="wide", initial_sidebar_state="collapsed")

# --- 2. INTEGRAÇÃO ---
try:
    CA_ID = st.secrets["conta_azul"]["client_id"]
    CA_SECRET = st.secrets["conta_azul"]["client_secret"]
except:
    st.error("Erro: Credenciais ausentes.")
    st.stop()

@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except: return None

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
        return None
    except: return None

# --- 3. BUSCA DE DADOS (FILTRO RESTRITO) ---
def buscar_dados_v2(endpoint, headers, params):
    todos_itens = []
    # FIXO: Apenas EM_ABERTO conforme solicitado (removemos ATRASADO)
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
            # Captura apenas o saldo devedor real
            total = item.get('total', 0)
            pago = item.get('pago', 0)
            saldo = total - pago
            
            # Validação dupla: status_traduzido e valor residual
            if saldo > 0 and str(item.get('status_traduzido', '')).upper() != 'RECEBIDO':
                todos_itens.append({
                    "Vencimento": item.get("data_vencimento"),
                    "Valor": saldo
                })
                
        if len(itens) < 100: break
        pagina += 1
    return todos_itens

# --- 4. INTERFACE ---
sh = get_sheet()
clientes = [r[0] for r in sh.get_all_values()[1:]] if sh else []

with st.sidebar:
    st.header("Configurações")
    # Forçamos o intervalo para hoje + 7 dias
    hoje = datetime.now().date()
    semana_que_vem = hoje + timedelta(days=7)
    
    data_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
    data_fim = st.date_input("Fim", semana_que_vem, format="DD/MM/YYYY")
    
    empresa = st.selectbox("Cliente Ativo", clientes)
    btn_sync = st.button("Sincronizar", type="primary")

st.title("Painel Financeiro JRM")

if empresa and (btn_sync or "sync_done" not in st.session_state):
    token = obter_token(empresa)
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        p = {"data_vencimento_de": data_ini, "data_vencimento_ate": data_fim}
        
        pagar_list = buscar_dados_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", headers, p)
        receber_list = buscar_dados_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers, p)
        
        df_p = pd.DataFrame(pagar_list)
        df_r = pd.DataFrame(receber_list)
        
        # Gráfico e Cards
        df_base = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
        val_p = df_p.groupby('Vencimento')['Valor'].sum() if not df_p.empty else pd.Series()
        val_r = df_r.groupby('Vencimento')['Valor'].sum() if not df_r.empty else pd.Series()
        
        df_base['Pagar'] = df_base['data'].dt.strftime('%Y-%m-%d').map(val_p).fillna(0)
        df_base['Receber'] = df_base['data'].dt.strftime('%Y-%m-%d').map(val_r).fillna(0)
        df_base['Saldo'] = df_base['Receber'] - df_base['Pagar']

        c1, c2, c3 = st.columns(3)
        fmt_br = lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        c1.metric("A Receber", fmt_br(df_base['Receber'].sum()))
        c2.metric("A Pagar", fmt_br(df_base['Pagar'].sum()))
        c3.metric("Saldo Período", fmt_br(df_base['Saldo'].sum()))

        fig = go.Figure()
        ttip = 'R$ %{y:,.2f}<extra></extra>'
        fig.add_trace(go.Bar(x=df_base['data'], y=df_base['Receber'], name='Receitas', marker_color='#2ecc71', hovertemplate=ttip))
        fig.add_trace(go.Bar(x=df_base['data'], y=df_base['Pagar'], name='Despesas', marker_color='#e74c3c', hovertemplate=ttip))
        fig.add_trace(go.Scatter(x=df_base['data'], y=df_base['Saldo'], name='Saldo', line=dict(color='#2C3E50', width=3), hovertemplate=ttip))

        fig.update_layout(
            separators=',.', hovermode="x unified",
            xaxis=dict(tickformat='%d/%m', showgrid=False),
            yaxis=dict(tickformat=',.2f', gridcolor='rgba(128,128,128,0.1)'),
            legend=dict(orientation="h", y=-0.2, x=0.5, xanchor="center"),
            margin=dict(l=60, r=20, t=20, b=80),
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        st.session_state.sync_done = True
