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

# Credenciais e Endpoints atualizados conforme orientação do suporte
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]

# Novo endpoint de login recomendado
AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api-v2.contaazul.com"

# Escopo obrigatório fixo
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

# --- FUNÇÕES DE BANCO DE DADOS (GOOGLE SHEETS) ---

def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na conexão com a planilha: {e}")
        return None

def update_refresh_token(empresa, novo_rt):
    sh = get_sheet()
    if not sh: return
    try:
        cell = sh.find(empresa)
        sh.update_cell(cell.row, 2, novo_rt)
    except:
        sh.append_row([empresa, novo_rt])

def get_access_token(empresa_nome):
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
    
    # URL de Autorização usando o endpoint /login e escopos corrigidos
    # Nota: O Streamlit lida com o encoding do link_button, mas os '+' no scope são literais
    params_auth = (
        f"?response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&scope={SCOPE}"
    )
    url_final = AUTH_URL + params_auth
    
    st.link_button("Vincular Nova Empresa", url_final, type="primary", use_container_width=True)
    st.divider()

# Captura o redirecionamento (Code na URL)
params = st.query_params
if "code" in params:
    code = params["code"]
    
    with st.expander("✨ Finalizar Novo Vínculo", expanded=True):
        st.info("Autorização detectada! Identifique a empresa para salvar.")
        nome_nova_empresa = st.text_input("Nome da Empresa (ex: Juvenal)")
        
        if st.button("Confirmar e Salvar na Planilha"):
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
                    st.success(f"Empresa '{nome_nova_empresa}' vinculada!")
                    st.query_params.clear() 
                    st.rerun()
                else:
                    st.error(f"Erro na troca do token: {res.text}")

# --- DASHBOARD E CONSULTA ---

with st.sidebar:
    st.header("📊 Filtros")
    sh = get_sheet()
    lista_empresas = []
    if sh:
        df_sheet = pd.DataFrame(sh.get_all_records())
        lista_empresas = df_sheet['empresa'].unique().tolist() if not df_sheet.empty else []

    sel_empresa = st.selectbox("Selecione a Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("De", datetime.now() - timedelta(days=7))
    d_fim = st.date_input("Até", datetime.now() + timedelta(days=30))

if st.button("🚀 Sincronizar Dados", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados = []
    
    for emp in alvos:
        token = get_access_token(emp)
        if not token: continue

        for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
            res = requests.get(f"{API_BASE_URL}/v1/financeiro/{endpoint}", 
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "expiration_date_from": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                    "expiration_date_to": d_fim.strftime('%Y-%m-%dT23:59:59Z')
                })
            
            if res.status_code == 200:
                for i in res.json():
                    dt = i.get('due_date') or i.get('expiration_date')
                    dados.append({
                        'Empresa': emp, 'Data': pd.to_datetime(dt[:10]),
                        'Tipo': tipo, 'Valor': float(i.get('value', 0)),
                        'Descrição': i.get('description', 'S/D')
                    })

    if dados:
        df = pd.DataFrame(dados)
        st.dataframe(df.sort_values('Data'), use_container_width=True)
    else:
        st.info("Nenhum dado encontrado.")

# --- BLOCO DE DEPURAÇÃO (DEBUG) ---
if st.button("🚀 Sincronizar Dados", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados = []
    
    for emp in alvos:
        token = get_access_token(emp)
        if not token: 
            st.error(f"❌ Não consegui renovar o acesso para {emp}. Tente vincular novamente.")
            continue

        for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
            url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
            res = requests.get(url, 
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "expiration_date_from": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                    "expiration_date_to": d_fim.strftime('%Y-%m-%dT23:59:59Z')
                })
            
            # Se não for 200 (Sucesso), mostra o que aconteceu
            if res.status_code != 200:
                st.error(f"Erro na API ({tipo} - {emp}): {res.status_code} - {res.text}")
                continue

            # Se for 200, processa os dados
            lista_retorno = res.json()
            if not lista_retorno:
                st.info(f"ℹ️ Sem lançamentos de {tipo} para {emp} no período selecionado.")
            
            for i in lista_retorno:
                dt = i.get('due_date') or i.get('expiration_date')
                dados.append({
                    'Empresa': emp, 'Data': pd.to_datetime(dt[:10]),
                    'Tipo': tipo, 'Valor': float(i.get('value', 0)),
                    'Descrição': i.get('description', 'S/D')
                })

    if dados:
        st.success(f"✅ {len(dados)} lançamentos encontrados!")
        st.dataframe(pd.DataFrame(dados).sort_values('Data'), use_container_width=True)
