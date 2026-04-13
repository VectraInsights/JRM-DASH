import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES E SEGURANÇA ---
try:
    CA_ID = st.secrets["conta_azul"]["client_id"]
    CA_SECRET = st.secrets["conta_azul"]["client_secret"]
    CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]
except:
    st.error("Erro: Verifique as credenciais no secrets.toml.")
    st.stop()

API_BASE_URL = "https://api-v2.contaazul.com" 
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
AUTH_URL = "https://auth.contaazul.com/login"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. CSS PARA COMPACTAÇÃO E CONTRASTE ---
st.markdown("""
    <style>
        /* Reduz respiro do topo e margens internas */
        .block-container {padding-top: 1rem !important; padding-bottom: 0rem !important;}
        h1 {margin-top: -45px; margin-bottom: 10px; font-size: 1.8rem !important;}
        
        /* Estilização dos Cards de Métricas */
        div[data-testid="stMetric"] {
            padding: 10px; 
            background: rgba(128, 128, 128, 0.08); 
            border-radius: 8px;
            border: 1px solid rgba(128, 128, 128, 0.2);
        }
        
        /* Garante que o texto das métricas seja legível em qualquer tema */
        [data-testid="stMetricValue"] { font-size: 1.6rem !important; }
    </style>
""", unsafe_allow_html=True)

# --- 3. INTEGRAÇÃO COM GOOGLE SHEETS (FLUXO DE CAIXA) ---
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        # Abre a planilha pelo link fornecido nas conversas anteriores
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na Planilha: {e}")
        return None

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value # Coluna B tem o Refresh Token
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt_atual})
        
        if res.status_code == 200:
            dados = res.json()
            # Se a API enviar um novo Refresh Token, atualiza a planilha imediatamente
            if dados.get('refresh_token') and dados['refresh_token'] != rt_atual:
                sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
        return None
    except:
        return None

# --- 4. BARRA LATERAL (FILTROS E LOGIN) ---
with st.sidebar:
    st.header("⚙️ Configurações")
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
    
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Login Conta Azul", url_auth, use_container_width=True)
    
    st.divider()
    data_inicio = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    data_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    btn_sincronizar = st.button("🔄 Sincronizar dados", use_container_width=True, type="primary")
    
    sh = get_sheet()
    emp_selecionada = None
    if sh:
        clientes = [r[0] for r in sh.get_all_values()[1:] if r]
        emp_selecionada = st.selectbox("Cliente Ativo", clientes)

# --- 5. ÁREA PRINCIPAL ---
st.title("Painel Financeiro JRM")

if emp_selecionada and btn_sincronizar:
    with st.spinner(f"Buscando {emp_selecionada}..."):
        token = obter_novo_access_token(emp_selecionada)
        
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            p = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
            
            res_p = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", headers=headers, params=p).json()
            res_r = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers=headers, params=p).json()
            
            # Processamento de Dados (Garante que dias sem movimento apareçam no gráfico)
            df_plot = pd.DataFrame({'data': pd.date_range(data_inicio, data_fim)})
            df_p = pd.DataFrame(res_p.get('itens', []))
            df_r = pd.DataFrame(res_r.get('itens', []))

            val_p = df_p.groupby('data_vencimento')['total'].sum() if not df_p.empty else pd.Series()
            val_r = df_r.groupby('data_vencimento')['total'].sum() if not df_r.empty else pd.Series()
            
            df_plot['Pagar'] = df_plot['data'].dt.strftime('%Y-%m-%d').map(val_p).fillna(0)
            df_plot['Receber'] = df_plot['data'].dt.strftime('%Y-%m-%d').map(val_r).fillna(0)
            df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

            # --- EXIBIÇÃO: CARDS ---
            c1, c2, c3 = st.columns(3)
            c1.metric("A Receber", f"R$ {df_plot['Receber'].sum():,.2f}")
            c2.metric("A Pagar", f"R$ {df_plot['Pagar'].sum():,.2f}")
            c3.metric("Saldo Período", f"R$ {df_plot['Saldo'].sum():,.2f}")

            # --- GRÁFICO PERSONALIZADO (ALTO CONTRASTE) ---
            fig = go.Figure()
            
            # Barras de Receita (Verde) e Despesa (Vermelho)
            fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
            fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
            
            # Linha de Tendência de Saldo
            fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo', 
                                     line=dict(color='#34495e', width=3),
                                     marker=dict(size=8, symbol='circle', line=dict(width=1, color='white'))))

            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                # Ajuste de Fonte para visibilidade no Modo Claro
                font=dict(color="#31333F", size=12),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                hovermode="x unified",
                xaxis=dict(showgrid=False, tickformat='%d/%m', tickfont=dict(color="#31333F")),
                yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.2)', tickfont=dict(color="#31333F")),
                height=400, # Altura otimizada para caber na tela
                margin=dict(l=10, r=10, t=10, b=10)
            )
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        else:
            st.error("Token expirado ou inválido. Tente vincular a conta novamente.")
elif not btn_sincronizar:
    st.info("👈 Selecione o cliente e clique em 'Sincronizar dados' para gerar o gráfico.")
