import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES TÉCNICAS ---
try:
    CA_ID = st.secrets["conta_azul"]["client_id"]
    CA_SECRET = st.secrets["conta_azul"]["client_secret"]
    CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]
except:
    st.error("Erro: Verifique as credenciais no arquivo secrets.toml.")
    st.stop()

API_BASE_URL = "https://api-v2.contaazul.com" 
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
AUTH_URL = "https://auth.contaazul.com/login"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. GESTÃO DA PLANILHA (FLUXO DE CAIXA) ---
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        # Conecta à planilha "Fluxo de Caixa"
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro de conexão com a planilha Fluxo de Caixa: {e}")
        return None

def salvar_refresh_token(empresa, refresh_token):
    sh = get_sheet()
    if not sh: return
    try:
        col_empresas = sh.col_values(1)
        nome_busca = empresa.strip().lower()
        linha_index = next((i + 1 for i, v in enumerate(col_empresas) if v.strip().lower() == nome_busca), -1)
        if linha_index > 0:
            sh.update_cell(linha_index, 2, refresh_token)
        else:
            sh.append_row([empresa, refresh_token])
    except: pass

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt_atual, "client_id": CA_ID, "client_secret": CA_SECRET})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token') and dados['refresh_token'] != rt_atual:
                salvar_refresh_token(empresa_nome, dados['refresh_token'])
            return dados['access_token']
        return None
    except: return None

# --- 3. BARRA LATERAL (FILTROS E AÇÕES) ---
with st.sidebar:
    st.header("⚙️ Configurações")
    
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
    
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Vincular Nova Conta", url_auth, use_container_width=True)
    
    st.divider()
    st.subheader("📅 Período")
    data_inicio = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    data_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    # Botão de Sincronizar movido para a barra lateral
    sincronizar = st.button("🔄 Sincronizar dados", use_container_width=True, type="primary")
    
    st.divider()
    sh = get_sheet()
    emp_selecionada = None
    if sh:
        try:
            dados_pl = sh.get_all_values()
            if len(dados_pl) > 1:
                df_pl = pd.DataFrame(dados_pl[1:], columns=dados_pl[0])
                emp_selecionada = st.selectbox("Cliente Ativo", df_pl.iloc[:, 0].unique().tolist())
        except: pass

# --- 4. ÁREA PRINCIPAL ---
st.title("Painel Financeiro JRM")

if emp_selecionada and sincronizar:
    with st.spinner(f"Sincronizando {emp_selecionada}..."):
        token = obter_novo_access_token(emp_selecionada)
        
        if token:
            headers = {"Authorization": f"Bearer {token}"}
            params = {
                "data_vencimento_de": data_inicio.strftime('%Y-%m-%d'),
                "data_vencimento_ate": data_fim.strftime('%Y-%m-%d'),
                "tamanho_pagina": 100
            }
            
            res_p = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", headers=headers, params=params)
            res_r = requests.get(f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers=headers, params=params)
            
            if res_p.status_code == 200 and res_r.status_code == 200:
                df_p_raw = pd.DataFrame(res_p.json().get('itens', []))
                df_r_raw = pd.DataFrame(res_r.json().get('itens', []))
                df_plot = pd.DataFrame({'data': pd.date_range(data_inicio, data_fim)})
                
                # Processamento Pagar/Receber
                for df_raw, col_name in [(df_p_raw, 'Pagar'), (df_r_raw, 'Receber')]:
                    if not df_raw.empty:
                        df_raw['data'] = pd.to_datetime(df_raw['data_vencimento'])
                        df_raw['valor'] = pd.to_numeric(df_raw['total'])
                        df_plot = df_plot.merge(df_raw.groupby('data')['valor'].sum(), on='data', how='left').rename(columns={'valor': col_name})
                    else: df_plot[col_name] = 0
                
                df_plot = df_plot.fillna(0)
                df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

                # --- 5. CARDS DE TOTAIS ---
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric("Total a Receber", f"R$ {df_plot['Receber'].sum():,.2f}")
                c2.metric("Total a Pagar", f"R$ {df_plot['Pagar'].sum():,.2f}")
                c3.metric("Saldo do Período", f"R$ {df_plot['Saldo'].sum():,.2f}")
                
                # --- 6. GRÁFICO (MODO UNIFICADO SEM LINHAS SPIKE) ---
                fig = go.Figure()
                fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Receber'], name='Receitas', marker_color='#2ecc71'))
                fig.add_trace(go.Bar(x=df_plot['data'], y=df_plot['Pagar'], name='Despesas', marker_color='#e74c3c'))
                fig.add_trace(go.Scatter(x=df_plot['data'], y=df_plot['Saldo'], name='Saldo', 
                                         line=dict(color='#34495e', width=4),
                                         marker=dict(size=12, symbol='circle', line=dict(width=2, color='white'))))

                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
                    hovermode="x unified",
                    xaxis=dict(showgrid=False, tickformat='%d/%m', showspikes=False),
                    yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.1)', showspikes=False),
                    height=550
                )
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            else:
                st.error("Erro ao carregar dados da API.")
        else:
            st.error("Falha na autenticação.")
elif not sincronizar:
    st.info("👈 Ajuste os filtros e clique em 'Sincronizar dados' na barra lateral.")
