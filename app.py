import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- CONFIGURAÇÕES DE AMBIENTE ---
st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# Substitua ou garanta que existam no seu st.secrets
CLIENT_ID = st.secrets['conta_azul']['client_id']
CLIENT_SECRET = st.secrets['conta_azul']['client_secret']
REDIRECT_URI = st.secrets['conta_azul']['redirect_uri']
API_BASE_URL = "https://api-v2.contaazul.com"
AUTH_URL = "https://auth.contaazul.com/oauth2/authorize"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"

# --- FUNÇÕES DE BANCO DE DADOS (GOOGLE SHEETS) ---

def get_sheet():
    """Conecta à planilha mestre."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na planilha: {e}")
        return None

def update_refresh_token(empresa, novo_rt):
    """Atualiza ou insere o refresh token na planilha."""
    sh = get_sheet()
    if not sh: return
    try:
        cell = sh.find(empresa)
        sh.update_cell(cell.row, 2, novo_rt)
    except:
        sh.append_row([empresa, novo_rt])

# --- LÓGICA DE TOKENS E API ---

def get_access_token(empresa_nome):
    """Gera um novo access_token usando o refresh_token salvo."""
    sh = get_sheet()
    cell = sh.find(empresa_nome)
    if not cell: return None
    
    rt_salvo = sh.cell(cell.row, 2).value
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    
    res = requests.post(TOKEN_URL, 
        headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": rt_salvo})

    if res.status_code == 200:
        data = res.json()
        update_refresh_token(empresa_nome, data['refresh_token'])
        return data['access_token']
    return None

# --- INTERFACE: VÍNCULO DE NOVA EMPRESA ---

with st.sidebar:
    st.header("🔗 Conexão Conta Azul")
    
    # URL de Autorização (Escopos conforme documentação)
    url_autorizacao = (
        f"{AUTH_URL}?scope=sales,financial,products,customers"
        f"&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code"
    )
    
    st.link_button("Vincular Empresa no Conta Azul", url_autorizacao, type="primary", use_container_width=True)
    st.divider()

# Captura o redirecionamento (Code na URL)
params = st.query_params
if "code" in params:
    code = params["code"]
    
    with st.expander("✨ Finalizar Novo Vínculo", expanded=True):
        st.write("Autorização recebida com sucesso! Agora, dê um nome para esta empresa:")
        nome_nova_empresa = st.text_input("Nome da Empresa", placeholder="Ex: Juvenal Transportes")
        
        if st.button("Confirmar e Salvar"):
            if nome_nova_empresa:
                auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                res = requests.post(TOKEN_URL, 
                    headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": REDIRECT_URI
                    })
                
                if res.status_code == 200:
                    data = res.json()
                    update_refresh_token(nome_nova_empresa, data['refresh_token'])
                    st.success(f"Empresa '{nome_nova_empresa}' vinculada e salva!")
                    st.query_params.clear() # Limpa a URL para não processar o mesmo código de novo
                    st.rerun()
                else:
                    st.error(f"Erro na troca do token: {res.text}")
            else:
                st.warning("Por favor, digite um nome.")

# --- INTERFACE: CONSULTA E DASHBOARD ---

with st.sidebar:
    st.header("📊 Filtros de Consulta")
    sh = get_sheet()
    if sh:
        df_sheet = pd.DataFrame(sh.get_all_records())
        lista_empresas = df_sheet['empresa'].unique().tolist() if not df_sheet.empty else []
    else:
        lista_empresas = []

    sel_empresa = st.selectbox("Selecione a Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("Vencimento De", datetime.now() - timedelta(days=7))
    d_fim = st.date_input("Vencimento Até", datetime.now() + timedelta(days=30))
    debug_mode = st.checkbox("Logs de Depuração")

if st.button("🚀 Consultar Fluxo de Caixa", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados_acumulados = []
    
    with st.spinner("Buscando dados na Conta Azul..."):
        for emp in alvos:
            token = get_access_token(emp)
            if not token: continue

            # Rotas oficiais da v2 conforme Financeiro.docx
            for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
                url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
                params_api = {
                    "expiration_date_from": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                    "expiration_date_to": d_fim.strftime('%Y-%m-%dT23:59:59Z')
                }
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params_api)
                
                if debug_mode:
                    st.write(f"Empresa: {emp} | Rota: {endpoint} | Status: {res.status_code}")
                
                if res.status_code == 200:
                    for lancamento in res.json():
                        # A API pode retornar due_date ou expiration_date dependendo da rota
                        data_venc = lancamento.get('due_date') or lancamento.get('expiration_date')
                        dados_acumulados.append({
                            'Empresa': emp,
                            'Vencimento': pd.to_datetime(data_venc[:10]),
                            'Tipo': tipo,
                            'Valor': float(lancamento.get('value', 0)),
                            'Descrição': lancamento.get('description', 'S/D')
                        })

    if dados_acumulados:
        df = pd.DataFrame(dados_acumulados)
        
        # Métricas de topo
        c1, c2, c3 = st.columns(3)
        total_rec = df[df['Tipo'] == 'Receber']['Valor'].sum()
        total_pag = df[df['Tipo'] == 'Pagar']['Valor'].sum()
        c1.metric("Receber Total", f"R$ {total_rec:,.2f}")
        c2.metric("Pagar Total", f"R$ {total_pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo Líquido", f"R$ {(total_rec - total_pag):,.2f}")

        # Visualização Gráfica
        df_agrupado = df.groupby(['Vencimento', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        fig = go.Figure()
        if 'Receber' in df_agrupado.columns:
            fig.add_trace(go.Bar(x=df_agrupado['Vencimento'], y=df_agrupado['Receber'], name='Receber', marker_color='#2ecc71'))
        if 'Pagar' in df_agrupado.columns:
            fig.add_trace(go.Bar(x=df_agrupado['Vencimento'], y=-df_agrupado['Pagar'], name='Pagar', marker_color='#e74c3c'))
        
        fig.update_layout(barmode='relative', title="Previsão de Fluxo de Caixa Diário", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        # Tabela completa
        st.subheader("Detalhamento dos Lançamentos")
        st.dataframe(df.sort_values('Vencimento'), use_container_width=True)
    else:
        st.warning("Nenhum dado encontrado para o período ou empresa selecionada.")
