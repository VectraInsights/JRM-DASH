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
        [data-testid="stHeader"], #MainMenu, footer { display: none !important; }
        .main .block-container { padding-top: 0rem !important; }

        /* MATA LINHAS DE HOVER E SPIKELINES */
        .hoverlayer line, .spikeline, .axislines {
            display: none !important;
            stroke-width: 0px !important;
            opacity: 0 !important;
        }
        
        div[data-testid="stMetric"] {
            background: rgba(128, 128, 128, 0.05); 
            border: 1px solid rgba(128, 128, 128, 0.2);
            padding: 15px; border-radius: 10px;
        }
    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO ---
@st.cache_resource(show_spinner=False)
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = st.secrets["google_sheets"]
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        
        # ID extraído da sua URL (mais estável que open_by_url)
        sheet_id = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
        return client.open_by_key(sheet_id).sheet1
    except Exception as e:
        # Armazena o erro para o debug
        st.session_state['last_error'] = str(e)
        return None

def format_br(valor):
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        ca = st.secrets["conta_azul"]
        auth_b64 = base64.b64encode(f"{ca['client_id']}:{ca['client_secret']}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt}, timeout=10)
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
    except: pass
    return None

def buscar_v2(endpoint, token, params):
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1})
    while True:
        try:
            res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params, timeout=15)
            if res.status_code != 200: break
            itens = res.json().get('itens', [])
            if not itens: break
            for i in itens:
                saldo = i.get('total', 0) - i.get('pago', 0)
                if saldo > 0: itens_acumulados.append({"Vencimento": i.get("data_vencimento"), "Valor": saldo})
            if len(itens) < 100: break
            params["pagina"] += 1
        except: break
    return itens_acumulados

# --- 3. LÓGICA DE INTERFACE E DEBUG ---
sh = get_sheet()
clientes = []

# Bloco de Debug visível apenas se expandido
with st.expander("🛠️ DEBUG DE CONEXÃO"):
    if "google_sheets" not in st.secrets:
        st.error("ERRO: Seção [google_sheets] não encontrada no Secrets.")
    
    if sh:
        st.success("Conexão Google Sheets: OK!")
        try:
            clientes = [r[0] for r in sh.get_all_values()[1:]]
            st.write(f"Empresas encontradas: {len(clientes)}")
        except Exception as e:
            st.error(f"Erro ao ler linhas: {e}")
    else:
        st.error("get_sheet() retornou None.")
        if 'last_error' in st.session_state:
            st.code(st.session_state['last_error'], language="bash")
        st.info("Dica: Verifique se o e-mail da conta de serviço é 'Editor' na planilha.")

# --- 4. FILTROS (BARRA LATERAL) ---
with st.sidebar:
    st.header("Fluxo de Caixa JRM")
    empresa_sel = st.selectbox("Selecione a Empresa", ["Todos os Clientes"] + clientes)
    
    hoje = datetime.now().date()
    with st.form("datas_form"):
        data_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
        data_fim = st.date_input("Fim", hoje + timedelta(days=17), format="DD/MM/YYYY")
        submit = st.form_submit_button("Sincronizar", type="primary")

st.title("Fluxo de Caixa")

# --- 5. EXECUÇÃO ---
alvo = (clientes if empresa_sel == "Todos os Clientes" else [empresa_sel]) if clientes else []
p_total, r_total = [], []

if submit and alvo:
    with st.spinner("Buscando dados no Conta Azul..."):
        for emp in alvo:
            tk = obter_token(emp)
            if tk:
                api_p = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
                p_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, api_p.copy()))
                r_total.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, api_p.copy()))

if p_total or r_total:
    df_plot = pd.DataFrame({'data': pd.date_range(data_ini, data_fim)})
    df_plot['data_str'] = df_plot['data'].dt.strftime('%Y-%m-%d')
    
    val_p = pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum() if p_total else pd.Series(dtype=float)
    val_r = pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum() if r_total else pd.Series(dtype=float)
    
    df_plot['Pagar'] = df_plot['data_str'].map(val_p).fillna(0)
    df_plot['Receber'] = df_plot['data_str'].map(val_r).fillna(0)
    df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

    c1, c2, c3 = st.columns(3)
    c1.metric("Total a Receber", format_br(df_plot['Receber'].sum()))
    c2.metric("Total a Pagar", format_br(df_plot['Pagar'].sum()))
    c3.metric("Saldo Líquido", format_br(df_plot['Saldo'].sum()))

    # --- 6. GRÁFICO ---
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
    fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
    fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo', line=dict(color='#34495e', width=3), mode='lines+markers'))

    fig.update_layout(
        hovermode="x",
        xaxis=dict(showgrid=False, fixedrange=True, tickformat='%d/%m', showspikes=False),
        yaxis=dict(showgrid=False, fixedrange=True, tickformat=',.2f', showspikes=False),
        legend=dict(orientation="h", y=-0.3, x=0.5, xanchor="center"),
        margin=dict(l=10, r=10, t=10, b=50),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        spikedistance=0
    )
    
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False, 'showSpikes': False})
else:
    if not submit:
        st.info("Selecione os filtros e clique em 'Sincronizar'.")
    else:
        st.warning("Nenhum dado encontrado para o período/empresa selecionada.")
