import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import secrets
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES TÉCNICAS (secrets.toml) ---
try:
    CA_ID = st.secrets["conta_azul"]["client_id"]
    CA_SECRET = st.secrets["conta_azul"]["client_secret"]
    CA_REDIRECT = st.secrets["conta_azul"]["redirect_uri"]
except:
    st.error("Erro: Verifique se o arquivo .streamlit/secrets.toml contém [conta_azul] com client_id, client_secret e redirect_uri.")
    st.stop()

API_BASE_URL = "https://api-v2.contaazul.com" 
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
AUTH_URL = "https://auth.contaazul.com/login"
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

st.set_page_config(page_title="BPO Dashboard JRM", layout="wide")

# --- 2. BANCO DE DADOS (GOOGLE SHEETS) ---
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        # Tente abrir pelo link exato fornecido anteriormente
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro de conexão com o Google Sheets: {e}. Verifique as permissões do Service Account.")
        return None

def salvar_refresh_token(empresa, refresh_token):
    sh = get_sheet()
    if not sh: return
    try:
        col_empresas = sh.col_values(1)
        nome_busca = empresa.strip().lower()
        
        # Procura se o cliente já existe (case-insensitive)
        linha_index = next((i + 1 for i, v in enumerate(col_empresas) if v.strip().lower() == nome_busca), -1)
        
        if linha_index > 0:
            # Se existe, atualiza a célula correspondente (coluna B)
            sh.update_cell(linha_index, 2, refresh_token)
            st.toast(f"🔄 Token de '{empresa}' sincronizado na planilha.")
        else:
            # Se não existe, cria uma nova linha
            sh.append_row([empresa, refresh_token])
            st.toast(f"✨ Nova conta '{empresa}' vinculada com sucesso!")
    except Exception as e:
        st.error(f"Erro ao salvar dados na planilha: {e}")

def obter_novo_access_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        # Busca o refresh token atual na planilha
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
        
        # Prepara a autenticação Basic
        auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
        
        # Faz a chamada de refresh
        res = requests.post(TOKEN_URL, 
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": rt_atual,
                "client_id": CA_ID,
                "client_secret": CA_SECRET
            }
        )
        
        if res.status_code == 200:
            dados = res.json()
            # Se a API retornou um novo refresh_token (rotação), salvamos na planilha
            if dados.get('refresh_token') and dados['refresh_token'] != rt_atual:
                salvar_refresh_token(empresa_nome, dados['refresh_token'])
            return dados['access_token']
        else:
            st.error(f"Erro no Refresh Token ({res.status_code}): {res.text}")
            return None
    except Exception as e:
        st.error(f"Erro ao obter novo token: {e}. Conta não encontrada ou erro de rede.")
        return None

# --- 3. BARRA LATERAL (SIDEBAR) ---
with st.sidebar:
    st.header("⚙️ Configurações")
    
    # Gerar state aleatório para segurança (OAuth2)
    if "oauth_state" not in st.session_state:
        st.session_state.oauth_state = secrets.token_urlsafe(16)
    
    # URL de Login Conta Azul
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CA_ID}&redirect_uri={CA_REDIRECT}&scope={SCOPE}&state={st.session_state.oauth_state}"
    st.link_button("🔑 Vincular Nova Conta", url_auth, type="primary", use_container_width=True)
    
    # Capturar o retorno do OAuth2 (código de autorização)
    params_url = st.query_params
    if "code" in params_url:
        st.divider()
        st.subheader("Finalizar Vínculo")
        nome_input = st.text_input("Identificação do Novo Cliente", placeholder="Ex: JTL")
        if st.button("Confirmar", use_container_width=True):
            if not nome_input:
                st.warning("Por favor, digite uma identificação para o cliente.")
            else:
                # Trocar o código pelo refresh_token final
                auth_b64 = base64.b64encode(f"{CA_ID}:{CA_SECRET}".encode()).decode()
                res = requests.post(TOKEN_URL, 
                    headers={
                        "Authorization": f"Basic {auth_b64}",
                        "Content-Type": "application/x-www-form-urlencoded"
                    },
                    data={
                        "grant_type": "authorization_code",
                        "code": params_url["code"],
                        "redirect_uri": CA_REDIRECT,
                        "client_id": CA_ID,
                        "client_secret": CA_SECRET
                    }
                )
                
                if res.status_code == 200:
                    salvar_refresh_token(nome_input, res.json()['refresh_token'])
                    # Limpa a URL e recarrega
                    st.query_params.clear()
                    st.rerun()
                else:
                    st.error(f"Erro ao trocar código por token: {res.text}")

    st.divider()
    
    # Filtros de Busca (com padrão brasileiro DD/MM/AAAA)
    st.subheader("📅 Filtros")
    data_inicio = st.date_input("Data Inicial", datetime.now(), format="DD/MM/YYYY")
    data_fim = st.date_input("Data Final", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.divider()
    
    # Listagem de Clientes Vinculados
    sh = get_sheet()
    emp_selecionada = None
    if sh:
        try:
            dados_pl = sh.get_all_values()
            if len(dados_pl) > 1:
                df_pl = pd.DataFrame(dados_pl[1:], columns=dados_pl[0])
                if not df_pl.empty:
                    # Lista dinâmica com base na coluna "empresa" (A)
                    lista_clientes = df_pl.iloc[:, 0].unique().tolist()
                    emp_selecionada = st.selectbox("Selecione o Cliente Ativo", lista_clientes)
        except: pass

# --- 4. ÁREA PRINCIPAL (DASHBOARD) ---
st.title("Painel Financeiro JRM")

if emp_selecionada:
    # Nome do botão simplificado
    if st.button("🔄 Sincronizar dados", use_container_width=True):
        with st.spinner(f"Processando dados de {emp_selecionada}..."):
            token = obter_novo_access_token(emp_selecionada)
            
            if token:
                headers = {"Authorization": f"Bearer {token}"}
                params = {
                    "data_vencimento_de": data_inicio.strftime('%Y-%m-%d'),
                    "data_vencimento_ate": data_fim.strftime('%Y-%m-%d'),
                    "tamanho_pagina": 100
                }
                
                # Chamadas paralelas para as APIs de Pagar e Receber
                url_pagar = f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar"
                url_receber = f"{API_BASE_URL}/v1/financeiro/eventos-financeiros/contas-a-receber/buscar"
                
                res_p = requests.get(url_pagar, headers=headers, params=params)
                res_r = requests.get(url_receber, headers=headers, params=params)
                
                if res_p.status_code == 200 and res_r.status_code == 200:
                    # Processamento de Dados
                    df_p_raw = pd.DataFrame(res_p.json().get('itens', []))
                    df_r_raw = pd.DataFrame(res_r.json().get('itens', []))
                    
                    # Cria o range completo de datas para o período selecionado
                    datas_range = pd.date_range(data_inicio, data_fim)
                    df_plot = pd.DataFrame({'data': datas_range})
                    
                    # Agrupar Pagamentos por data
                    if not df_p_raw.empty:
                        df_p_raw['data'] = pd.to_datetime(df_p_raw['data_vencimento'])
                        df_p_raw['valor'] = pd.to_numeric(df_p_raw['total'])
                        df_p_agrupado = df_p_raw.groupby('data')['valor'].sum().reset_index()
                        df_plot = df_plot.merge(df_p_agrupado, on='data', how='left').rename(columns={'valor': 'Pagar'})
                    else: df_plot['Pagar'] = 0
                    
                    # Agrupar Recebimentos por data
                    if not df_r_raw.empty:
                        df_r_raw['data'] = pd.to_datetime(df_r_raw['data_vencimento'])
                        df_r_raw['valor'] = pd.to_numeric(df_r_raw['total'])
                        df_r_agrupado = df_r_raw.groupby('data')['valor'].sum().reset_index()
                        df_plot = df_plot.merge(df_r_agrupado, on='data', how='left').rename(columns={'valor': 'Receber'})
                    else: df_plot['Receber'] = 0
                    
                    # Tratar vazios e calcular saldo
                    df_plot = df_plot.fillna(0)
                    df_plot['Saldo'] = df_plot['Receber'] - df_plot['Pagar']

                    # --- 5. CARDS DE TOTAIS NO TOPO (PAGAR E RECEBER) ---
                    st.divider()
                    col_r, col_p, col_s = st.columns(3)
                    
                    total_receber = df_plot['Receber'].sum()
                    total_pagar = df_plot['Pagar'].sum()
                    total_saldo = df_plot['Saldo'].sum()
                    
                    col_r.metric("Total a Receber", f"R$ {total_receber:,.2f}")
                    col_p.metric("Total a Pagar", f"R$ {total_pagar:,.2f}")
                    col_s.metric("Saldo do Período", f"R$ {total_saldo:,.2f}")
                    
                    st.write("") # Espaçamento

                    # --- 6. GRÁFICO PLOTLY INTERATIVO (FLUXO DE CAIXA) ---
                    fig = go.Figure()

                    # Barras de Recebimentos (Verde)
                    fig.add_trace(go.Bar(
                        x=df_plot['data'], 
                        y=df_plot['Receber'],
                        name='Recebimentos', 
                        marker_color='#2ecc71', # Verde Conta Azul
                        hovertemplate='Recebimentos: R$ %{y:,.2f}<extra></extra>'
                    ))

                    # Barras de Pagamentos (Vermelho)
                    fig.add_trace(go.Bar(
                        x=df_plot['data'], 
                        y=df_plot['Pagar'],
                        name='Pagamentos', 
                        marker_color='#e74c3c', # Vermelho Conta Azul
                        hovertemplate='Pagamentos: R$ %{y:,.2f}<extra></extra>'
                    ))

                    # Linha de Saldo com bolinhas
                    fig.add_trace(go.Scatter(
                        x=df_plot['data'], 
                        y=df_plot['Saldo'],
                        name='Saldo', 
                        line=dict(color='#34495e', width=4), # Azul Escuro
                        marker=dict(size=12, symbol='circle', line=dict(width=2, color='white')),
                        hovertemplate='Saldo: R$ %{y:,.2f}<extra></extra>'
                    ))

                    # Layout Personalizado: Cards unificados no hover
                    fig.update_layout(
                        template="plotly_dark", # Tema escuro nativo do Plotly
                        paper_bgcolor='rgba(0,0,0,0)', # Fundo transparente
                        plot_bgcolor='rgba(0,0,0,0)', # Fundo transparente
                        margin=dict(l=10, r=10, t=20, b=10),
                        # Legenda discreta na parte de baixo
                        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5),
                        # HOVERMODE UNIFIED: O card flutuante unificado que você pediu
                        hovermode="x unified",
                        # Remover as linhas cruzadas (spikes) para visual limpo
                        xaxis=dict(showgrid=False, tickformat='%d/%m', showspikes=False),
                        yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.1)', showspikes=False),
                        height=550
                    )

                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
                    
                    # --- 7. TABELA DETALHADA (A RECEBER) ---
                    st.divider()
                    st.subheader("Detalhamento: A Receber no Período")
                    
                    if not df_r_raw.empty:
                        # Selecionar e renomear colunas para padrão BR
                        df_r_view = df_r_raw[['descricao', 'total', 'data_vencimento', 'status_traduzido']].copy()
                        df_r_view.columns = ['Descrição', 'Valor (R$)', 'Vencimento', 'Status']
                        
                        # Formatar data de vencimento para DD/MM/AAAA
                        df_r_view['Vencimento'] = pd.to_datetime(df_r_view['Vencimento']).dt.strftime('%d/%m/%Y')
                        # Formatar valor monetário
                        df_r_view['Valor (R$)'] = df_r_view['Valor (R$)'].apply(lambda x: f"R$ {x:,.2f}")
                        
                        st.dataframe(df_r_view, use_container_width=True, hide_index=True)
                    else:
                        st.info("Nenhum lançamento 'A Receber' encontrado para o período informado.")

                else:
                    st.error(f"Erro ao buscar dados das APIs. Pagar: {res_p.status_code}, Receber: {res_r.status_code}")
            else:
                st.error("Token expirado ou inválido. Por favor, vincule a conta novamente ou verifique as credenciais.")
else:
    st.info("👈 Selecione um cliente na barra lateral para carregar o painel financeiro.")
