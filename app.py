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
# DEVE SER A PRIMEIRA LINHA
st.set_page_config(page_title="BPO Dashboard", layout="wide")

# Inicialização de estados
if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

# Cores dinâmicas baseadas no tema para CSS Injetado
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"
input_fill = "#1e1e1e" if st.session_state.theme == 'dark' else "#ffffff"
border_color = "#444" if st.session_state.theme == 'dark' else "#ccc"

# --- 2. CSS INJETADO E BOTÃO DE TEMA FLUTUANTE ---
st.markdown(f"""
    <style>
        /* Esconde header padrão para liberar o canto superior direito */
        header {{visibility: hidden;}}
        #MainMenu, footer {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        
        /* Força a Barra Lateral a seguir o tema */
        {{
            background-color: {side_bg} !important;
            border-right: 1px solid {border_color};
        }}
        * {{ color: {txt} !important; }}
        
        /* Corrige visibilidade dos Inputs (Select, Date) */
        .stSelectbox div,
        .stDateInput div {{
            background-color: {input_fill} !important;
            color: {txt} !important;
            border-color: {border_color} !important;
        }}

        /* FIX: CORRIGE O FUNDO BRANCO DE TODOS OS BOTÕES */
        div button {{
            background-color: {input_fill} !important;
            color: {txt} !important;
            border: 1px solid {border_color} !important;
        }}
        div button:hover {{
            border-color: {txt} !important;
        }}

        /* FIX: FIXA O PRIMEIRO BOTÃO (BOTÃO DE TEMA) NO CANTO SUPERIOR DIREITO */
        section.main div > div:first-child div button {{
            position: fixed;
            top: 15px;
            right: 15px;
            z-index: 999999;
            width: 45px;
            height: 45px;
            border-radius: 8px !important;
            opacity: 0.7;
            transition: 0.3s;
        }}
        section.main div > div:first-child div button:hover {{
            opacity: 1;
        }}

        /* FIX: CORRIGE O FUNDO DO CHECKBOX DISCRETO E REMOVE MARGENS */
        div div {{
            background-color: {input_fill} !important;
            border: 1px solid {border_color} !important;
        }}
        
        /* Container de Debug */
        .debug-container {{
            border: 2px solid #ff4b4b;
            padding: 15px;
            border-radius: 10px;
            margin-top: 10px;
            background-color: rgba(255, 75, 75, 0.05);
        }}
        .stMetric {{ background-color: {side_bg}; padding: 15px; border-radius: 10px; border: 1px solid {border_color}; }}
    </style>
    """, unsafe_allow_html=True)

# BOTÃO DE TEMA: DEVE SER O PRIMEIRO BOTÃO RENDERIZADO PARA O CSS FUNCIONAR E FIXÁ-LO NO CANTO
if st.button("🌓", key="theme_toggle"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()

# --- 3. INTEGRAÇÕES (API & GOOGLE SHEETS) ---
CLIENT_ID = st.secrets
CLIENT_SECRET = st.secrets
REDIRECT_URI = st.secrets
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
B64_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

@st.cache_resource
def get_sheet():
    scope =
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets), scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

def update_token_sheet(empresa, rt):
    sh = get_sheet()
    try:
        cell = sh.find(empresa)
        sh.update_cell(cell.row, 2, rt)
    except:
        sh.append_row()

def get_new_access_token(empresa):
    sh = get_sheet()
    try:
        cell = sh.find(empresa)
        rt_atual = sh.cell(cell.row, 2).value
        
        url = "https://auth.contaazul.com/oauth2/token"
        res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, 
                            data={"grant_type": "refresh_token", "refresh_token": rt_atual})
        
        if res.status_code == 200:
            data = res.json()
            update_token_sheet(empresa, data.get("refresh_token"))
            return data.get("access_token")
        return None
    except:
        return None

# --- 4. BARRA LATERAL (FILTROS E ADM) ---
with st.sidebar:
    st.title("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas_list = df_db.unique().tolist() if not df_db.empty else []
    except:
        empresas_list = []
        st.error("Erro ao carregar planilha.")
        
    selecao = st.selectbox("Empresa", + empresas_list)
    
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    # Empurra o conteúdo para baixo
    st.markdown('<div style="height: 60vh;"></div>', unsafe_allow_html=True)
    st.divider()
    
    # CHECKBOX DISCRETO NO LUGAR DO BOTÃO DE OLHO (Sem escrita, gerencia o adm_mode nativamente)
    st.checkbox(" ", key="adm_mode", label_visibility="collapsed")

# --- 5. ÁREA ADMINISTRATIVA ---
st.title("📊 Fluxo de Caixa BPO")

q_params = st.query_params
if "code" in q_params:
    st.info("🎯 Conexão detectada! Finalize o cadastro abaixo:")
    with st.container(border=True):
        nome_emp = st.text_input("Nome exato da Empresa para salvar:")
        if st.button("Confirmar e Salvar Nova Empresa", type="primary"):
            if nome_emp:
                r = requests.post("https://auth.contaazul.com/oauth2/token", 
                                  headers={"Authorization": f"Basic {B64_AUTH}"},
                                  data={"grant_type": "authorization_code", "code": q_params, "redirect_uri": REDIRECT_URI})
                if r.status_code == 200:
                    update_token_sheet(nome_emp, r.json().get("refresh_token"))
                    st.success(f"Empresa {nome_emp} conectada com sucesso!")
                    time.sleep(1)
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error("Erro ao trocar código por token. Verifique o Redirect URI.")
            else:
                st.error("Por favor, digite um nome.")

# Exibição do Módulo Administrativo (Condicionado ao Checkbox discreto)
if st.session_state.adm_mode:
    with st.container(border=True):
        st.subheader("🔑 Área do Administrador")
        pwd = st.text_input("Senha", type="password")
        if pwd == "8429coconoiaKc#":
            st.success("Acesso Liberado")
            st.link_button("🔌 Conectar Nova Empresa (Conta Azul)", 
                           f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 6. PROCESSAMENTO DE DADOS (CONSULTA API) ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else
    
    st.markdown('<div class="debug-container">', unsafe_allow_html=True)
    st.subheader("🛠️ Log de Depuração")
    
    for emp in lista_alvo:
        st.write(f"--- **Processando:** {emp} ---")
        token = get_new_access_token(emp)
        
        if token:
            time.sleep(0.5)
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            params = {
                "data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'),
                "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
            }
            headers = {"Authorization": f"Bearer {token}", "Cache-Control": "no-cache"}
            
            res = requests.get(url, headers=headers, params=params)
            
            if res.status_code == 200:
                itens = res.json()
                st.write(f"📊 Sucesso: {len(itens)} lançamentos obtidos.")
                for lanc in itens:
                    if isinstance(lanc, dict):
                        v = lanc.get('valor', 0)
                        tp = lanc.get('tipo')
                        dt = lanc.get('data_vencimento')
                        if dt and tp:
                            data_points.append({
                                'Data': pd.to_datetime(dt),
                                'Tipo': 'Recebimentos' if tp == 'RECEBER' else 'Pagamentos',
                                'Valor': float(v)
                            })
            else:
                st.error(f"❌ Erro {res.status_code} na API da Conta Azul para {emp}.")
        else:
            st.error(f"❌ Não foi possível obter token válido para {emp}.")
    
    st.markdown('</div>', unsafe_allow_html=True)

   # --- 7. DASHBOARD VISUAL (MÉTRICAS, GRÁFICO E TABELA) ---
    if data_points:
        df = pd.DataFrame(data_points)
        # Agrupa por data e tipo, depois reorganiza as colunas
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        
        # Garante que as colunas existam mesmo se não houver lançamentos de um tipo
        for col in ['Recebimentos', 'Pagamentos']:
            if col not in df_daily.columns:
                df_daily[col] = 0.0
        
        df_daily = df_daily.sort_values('Data')
        
        # Cálculos de Totais e Saldo
        total_rec = df_daily['Recebimentos'].sum()
        total_pag = df_daily['Pagamentos'].sum()
        df_daily['Saldo Diário'] = df_daily['Recebimentos'] - df_daily['Pagamentos']
        df_daily['Acumulado'] = df_daily['Saldo Diário'].cumsum()
        
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {total_rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {total_pag:,.2f}")
        c3.metric("Saldo do Período", f"R$ {(total_rec - total_pag):,.2f}")

        # Gráfico
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data'], y=df_daily['Recebimentos'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data'], y=-df_daily['Pagamentos'], name='Pagar', marker_color='#EF553B'))
        fig.add_trace(go.Scatter(x=df_daily['Data'], y=df_daily['Acumulado'], name='Saldo Acumulado', line=dict(color='#34495e', width=3)))
        
        fig.update_layout(
            barmode='relative', 
            template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
            legend=dict(orientation="h", y=-0.2), 
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tabela (Aqui estava o erro de sintaxe)
        st.subheader("Detalhamento por Dia")
        df_tab = df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Acumulado']].copy()
        df_tab['Data'] = df_tab['Data'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_tab, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
