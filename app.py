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

# --- 2. FUNÇÕES DE INTEGRAÇÃO ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = dict(st.secrets["google_sheets"])
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        # Substitua pela sua URL real da planilha
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro ao conectar ao Google Sheets: {e}")
        return None

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        # Credenciais do secrets
        cid = st.secrets["conta_azul"]["client_id"]
        sec = st.secrets["conta_azul"]["client_secret"]
        
        auth_b64 = base64.b64encode(f"{cid}:{sec}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
            
        if res.status_code == 200:
            dados = res.json()
            novo_rt = dados.get('refresh_token')
            if novo_rt:
                sh.update_cell(cell.row, 2, novo_rt)
            return dados['access_token']
        return None
    except:
        return None

def buscar_contas(endpoint, token, params):
    todos_itens = []
    headers = {"Authorization": f"Bearer {token}"}
    params["status"] = "EM_ABERTO"
    params["tamanho_pagina"] = 100
    pagina = 1
    
    while True:
        params["pagina"] = pagina
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        itens = res.json().get('itens', [])
        if not itens: break
        
        for i in itens:
            saldo = i.get('total', 0) - i.get('pago', 0)
            if saldo > 0:
                todos_itens.append({"Vencimento": i.get("data_vencimento"), "Valor": saldo})
        if len(itens) < 100: break
        pagina += 1
    return todos_itens

# --- 3. BARRA LATERAL COM TRAVA (FORMULÁRIO) ---
sh = get_sheet()
if sh:
    clientes_lista = [r[0] for r in sh.get_all_values()[1:]] # Pula o cabeçalho
else:
    clientes_lista = []

with st.sidebar:
    with st.form("filtro_fluxo"):
        st.subheader("Parâmetros de Consulta")
        hoje = datetime.now().date()
        
        # O formulário impede que estes campos atualizem o app ao serem clicados
        data_i = st.date_input("Data Inicial", hoje, format="DD/MM/YYYY")
        data_f = st.date_input("Data Final", hoje + timedelta(days=7), format="DD/MM/YYYY")
        
        opcoes = ["Todos os Clientes"] + clientes_lista
        selecionado = st.selectbox("Empresa", opcoes)
        
        # Botão de gatilho
        btn_atualizar = st.form_submit_button("Atualizar", type="primary")

# --- 4. LÓGICA DE EXECUÇÃO ---
st.title("Fluxo de Caixa")

# Só processa se clicar no botão OU se for a primeira vez que o app abre
if btn_atualizar or "iniciado" not in st.session_state:
    st.session_state.iniciado = True
    
    alvo = clientes_lista if selecionado == "Todos os Clientes" else [selecionado]
    p_final, r_final = [], []
    
    with st.spinner(f"Processando {selecionado}..."):
        for emp in alvo:
            token = obter_token(emp)
            if token:
                params = {
                    "data_vencimento_de": data_i.strftime('%Y-%m-%d'),
                    "data_vencimento_ate": data_f.strftime('%Y-%m-%d')
                }
                p_final.extend(buscar_contas("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, params))
                r_final.extend(buscar_contas("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, params))

    if p_final or r_final:
        # Criar DataFrame base para o gráfico
        datas = pd.date_range(data_i, data_f)
        df = pd.DataFrame({'data': datas, 'data_str': datas.strftime('%Y-%m-%d')})
        
        # Agrupar valores por data
        s_p = pd.DataFrame(p_final).groupby('Vencimento')['Valor'].sum() if p_final else pd.Series()
        s_r = pd.DataFrame(r_final).groupby('Vencimento')['Valor'].sum() if r_final else pd.Series()
        
        df['Pagar'] = df['data_str'].map(s_p).fillna(0)
        df['Receber'] = df['data_str'].map(s_r).fillna(0)
        df['Saldo'] = df['Receber'] - df['Pagar']

        # Cards de Resumo
        c1, c2, c3 = st.columns(3)
        moeda = lambda x: f"R$ {x:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        c1.metric("Total a Receber", moeda(df['Receber'].sum()))
        c2.metric("Total a Pagar", moeda(df['Pagar'].sum()))
        c3.metric("Saldo do Período", moeda(df['Saldo'].sum()))

        # Gráfico Consolidado
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df['data'], y=df['Receber'], name='Receitas', marker_color='#2ecc71'))
        fig.add_trace(go.Bar(x=df['data'], y=df['Pagar'], name='Despesas', marker_color='#e74c3c'))
        fig.add_trace(go.Scatter(x=df['data'], y=df['Saldo'], name='Saldo Líquido', line=dict(color='#2C3E50', width=3)))
        
        fig.update_layout(
            hovermode="x unified",
            xaxis=dict(tickformat='%d/%m', showgrid=False),
            yaxis=dict(tickformat=',.2f', gridcolor='rgba(0,0,0,0.05)'),
            legend=dict(orientation="h", y=-0.2),
            margin=dict(l=20, r=20, t=20, b=20),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Nenhum dado encontrado para os critérios selecionados.")
