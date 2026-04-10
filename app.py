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

# Inicialização de estados
if 'theme' not in st.session_state: st.session_state.theme = 'dark'
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

# Cores dinâmicas baseadas no tema para CSS Injetado
bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
side_bg = "#262730" if st.session_state.theme == 'dark' else "#f0f2f6"
txt = "#ffffff" if st.session_state.theme == 'dark' else "#31333F"
input_fill = "#1e1e1e" if st.session_state.theme == 'dark' else "#ffffff"

# Injeção de CSS para corrigir Modo Claro, Barra Lateral e Botão de Tema Flutuante
st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        
        /* Força a Barra Lateral a seguir o tema */
        [data-testid="stSidebar"] {{
            background-color: {side_bg} !important;
            border-right: 1px solid #444;
        }}
        [data-testid="stSidebar"] * {{ color: {txt} !important; }}
        
        /* Corrige visibilidade dos Inputs (Select, Date) em Modo Claro na Sidebar */
        [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"],
        [data-testid="stSidebar"] .stDateInput div {{
            background-color: {input_fill} !important;
            color: {txt} !important;
            border-radius: 5px;
        }}
        [data-testid="stSidebar"] label p {{ color: {txt} !important; }}

        /* Botão de Tema Flutuante Minimalista no Canto Superior Direito */
        .st-emotion-cache-12fmjuu {{ display: none; }} /* Esconde menu original se houver */
        .floating-theme {{
            position: fixed;
            top: 10px;
            right: 15px;
            z-index: 1000000; /* Garante que fique acima de tudo */
        }}
        .floating-theme button {{
            background: transparent !important;
            border: 1px solid #888 !important;
            border-radius: 5px;
            cursor: pointer;
            width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px !important;
            opacity: 0.5;
            transition: 0.2s;
        }}
        .floating-theme button:hover {{ opacity: 1; border-color: {txt} !important; }}

        /* Container de Debug */
        .debug-container {{
            border: 2px solid #ff4b4b;
            padding: 15px;
            border-radius: 10px;
            margin-top: 10px;
            background-color: rgba(255, 75, 75, 0.05);
        }}
        
        /* Metrics mais bonitas */
        .stMetric {{ background-color: {side_bg}; padding: 15px; border-radius: 10px; border: 1px solid #444; }}

        /* Espaçador para o olho ficar no fim da sidebar */
        .sidebar-spacer {{ height: 80vh; }}
    </style>
    """, unsafe_allow_html=True)

# Botão de Tema flutuante no canto superior direito
st.markdown('<div class="floating-theme">', unsafe_allow_html=True)
if st.button("🌓", key="theme_toggle"):
    st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
    st.rerun()
st.markdown('</div>', unsafe_allow_html=True)

# --- 2. INTEGRAÇÕES (API & GOOGLE SHEETS) ---
# (Assumindo que CLIENT_ID, CLIENT_SECRET, REDIRECT_URI e credenciais do sheets estão nos Secrets)
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

def get_new_access_token(empresa):
    """Busca o refresh_token atual na planilha e gera um novo access_token"""
    sh = get_sheet()
    try:
        cell = sh.find(empresa)
        rt_atual = sh.cell(cell.row, 2).value
        
        url = "https://auth.contaazul.com/oauth2/token"
        res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, 
                            data={"grant_type": "refresh_token", "refresh_token": rt_atual})
        
        if res.status_code == 200:
            data = res.json()
            # Salva o novo refresh_token para não precisar re-autenticar depois de mudar o código
            update_token_sheet(empresa, data.get("refresh_token"))
            return data.get("access_token")
        return None
    except:
        return None

# --- 3. BARRA LATERAL (FILTROS E ADM) ---
with st.sidebar:
    st.title("Filtros")
    try:
        df_db = pd.DataFrame(get_sheet().get_all_records())
        empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    except:
        empresas_list = []
        st.error("Erro ao carregar planilha.")
        
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas_list)
    
    # Data de início deve ser o dia atual (hoje)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    # Empurra o conteúdo para baixo
    st.markdown('<div style="height: 60vh;"></div>', unsafe_allow_html=True)
    
    st.divider()
    # Botão ADM discreto (ícone olho) no fim da barra lateral
    if st.button("👁️", key="adm_eye_discrete", help="Acessar Área Administrativa"):
        st.session_state.adm_mode = not st.session_state.adm_mode
        st.rerun()

# --- 4. ÁREA ADMINISTRATIVA ---
st.title("📊 Fluxo de Caixa BPO")

# Lógica de Captura de Retorno do Login da Conta Azul (Código de autorização)
q_params = st.query_params
if "code" in q_params:
    st.info("🎯 Conexão detectada! Finalize o cadastro abaixo:")
    with st.container(border=True):
        nome_emp = st.text_input("Nome exato da Empresa para salvar:")
        if st.button("Confirmar e Salvar Nova Empresa", type="primary"):
            if nome_emp:
                r = requests.post("https://auth.contaazul.com/oauth2/token", 
                                  headers={"Authorization": f"Basic {B64_AUTH}"},
                                  data={"grant_type": "authorization_code", "code": q_params["code"], "redirect_uri": REDIRECT_URI})
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

# Exibição do Módulo Administrativo
if st.session_state.adm_mode:
    with st.container(border=True):
        st.subheader("🔑 Área do Administrador")
        pwd = st.text_input("Senha", type="password")
        if pwd == "8429coconoiaKc#":
            st.success("Acesso Liberado")
            st.link_button("🔌 Conectar Nova Empresa (Conta Azul)", 
                           f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

# --- 5. PROCESSAMENTO DE DADOS (CONSULTA API) ---
if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    # Início do Bloco de Debug com Contorno
    st.markdown('<div class="debug-container">', unsafe_allow_html=True)
    st.subheader("🛠️ Log de Depuração")
    
    for emp in lista_alvo:
        st.write(f"--- **Processando:** {emp} ---")
        token = get_new_access_token(emp)
        
        if token:
            # Pequena pausa para garantir a sincronização da API da Conta Azul (resolveu erros passados)
            time.sleep(0.5)

            # Usando endpoint v1/lancamentos para robustez (confirmado em interações anteriores)
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            # Formatação de datas para API (sem horas)
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
                        tp = lanc.get('tipo') # Pagar or Receber
                        dt = lanc.get('data_vencimento')
                        if dt and tp:
                            data_points.append({
                                'Data': pd.to_datetime(dt),
                                'Tipo': 'Recebimentos' if tp == 'RECEBER' else 'Pagamentos',
                                'Valor': float(v)
                            })
            else:
                st.error(f"❌ Erro {res.status_code} na API da Conta Azul para {emp}.")
                # st.json(res.json()) # Ativar para ver o erro técnico completo
        else:
            st.error(f"❌ Não foi possível obter token válido para {emp}.")
    
    st.markdown('</div>', unsafe_allow_html=True)

    # --- 6. DASHBOARD VISUAL (MÉTRICAS, GRÁFICO E TABELA) ---
    if data_points:
        df = pd.DataFrame(data_points)
        df_daily = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        for col in ['Recebimentos', 'Pagamentos']:
            if col not in df_daily: df_daily[col] = 0
        
        df_daily = df_daily.sort_values('Data')
        
        # Cálculo de Saldos
        total_rec = df_daily['Recebimentos'].sum()
        total_pag = df_daily['Pagamentos'].sum()
        df_daily['Saldo Diário'] = df_daily['Recebimentos'] - df_daily['Pagamentos']
        df_daily['Acumulado'] = df_daily['Saldo Diário'].cumsum()
        
        # Dashboard Visual
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {total_rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {total_pag:,.2f}")
        c3.metric("Saldo do Período", f"R$ {(total_rec - total_pag):,.2f}")

        # Gráfico (Plotly híbrido Barras + Linha Saldo)
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_daily['Data'], y=df_daily['Recebimentos'], name='Receber', marker_color='#00CC96'))
        fig.add_trace(go.Bar(x=df_daily['Data'], y=-df_daily['Pagamentos'], name='Pagar', marker_color='#EF553B')) # Mostra negativo no gráfico
        fig.add_trace(go.Scatter(x=df_daily['Data'], y=df_daily['Acumulado'], name='Saldo Acumulado', line=dict(color='#34495e', width=3)))
        
        fig.update_layout(
            barmode='relative', 
            template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white",
            legend=dict(orientation="h", y=-0.2), 
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)

        # Tabela Formatada (Sem Horas)
        st.subheader("Detalhamento por Dia")
        df_tab = df_daily[['Data', 'Recebimentos', 'Pagamentos', 'Acumulado']].copy()
        # Formata a data para exibir apenas o dia (remove as horas)
        df_tab['Data'] = df_tab['Data'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_tab, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
