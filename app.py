import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- CONFIGURAÇÕES DE PÁGINA ---
st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# Configurações da API (Devem estar no st.secrets)
CLIENT_ID = st.secrets['conta_azul']['client_id']
CLIENT_SECRET = st.secrets['conta_azul']['client_secret']
REDIRECT_URI = st.secrets['conta_azul']['redirect_uri'] # Ex: https://seu-app.streamlit.app/
API_BASE_URL = "https://api-v2.contaazul.com"
AUTH_URL = "https://auth.contaazul.com/oauth2/authorize"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"

# --- FUNÇÕES DE CONEXÃO ---

def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na planilha: {e}")
        return None

def save_to_sheet(empresa, refresh_token):
    sh = get_sheet()
    if not sh: return
    cell = sh.find(empresa)
    if cell:
        sh.update_cell(cell.row, 2, refresh_token)
    else:
        sh.append_row([empresa, refresh_token])

def get_access_token(empresa_nome):
    """Renova o access_token usando o refresh_token da planilha."""
    sh = get_sheet()
    cell = sh.find(empresa_nome)
    if not cell: return None
    
    rt = sh.cell(cell.row, 2).value
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    
    res = requests.post(TOKEN_URL, 
        headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": rt})

    if res.status_code == 200:
        data = res.json()
        save_to_sheet(empresa_nome, data['refresh_token']) # Sincroniza novo RT
        return data['access_token']
    return None

# --- FLUXO DE AUTORIZAÇÃO DIRETA ---

st.sidebar.title("🔗 Conectar Conta Azul")

# 1. Gerar Link de Autorização
state = st.sidebar.text_input("Apelido da Empresa (ex: Juvenal)")
auth_link = f"{AUTH_URL}?scope=sales,financial,products,customers&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&state={state}"

if state:
    st.sidebar.markdown(f'[**Clique aqui para Autorizar {state}**]({auth_link})')

# 2. Capturar Código da URL (Redirect)
query_params = st.query_params
if "code" in query_params and "state" in query_params:
    code = query_params["code"]
    empresa_origem = query_params["state"]
    
    if st.sidebar.button(f"Confirmar Vínculo de {empresa_origem}"):
        auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI
            })
        
        if res.status_code == 200:
            tokens = res.json()
            save_to_sheet(empresa_origem, tokens['refresh_token'])
            st.success(f"Empresa {empresa_origem} vinculada e salva na planilha!")
            st.query_params.clear() # Limpa a URL
        else:
            st.error("Erro ao trocar código por token.")

st.sidebar.divider()

# --- FILTROS E DASHBOARD ---

with st.sidebar:
    sh = get_sheet()
    df_sheet = pd.DataFrame(sh.get_all_records()) if sh else pd.DataFrame()
    empresas_list = df_sheet['empresa'].unique().tolist() if not df_sheet.empty else []
    
    sel_empresa = st.selectbox("Empresa para Consulta", ["TODAS"] + empresas_list)
    d_inicio = st.date_input("Início", datetime.now() - timedelta(days=7))
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=30))
    debug_mode = st.checkbox("Modo Depuração")

if st.button("🚀 Sincronizar Fluxo de Caixa", type="primary"):
    alvos = empresas_list if sel_empresa == "TODAS" else [sel_empresa]
    dados_totais = []
    
    for emp in alvos:
        token = get_access_token(emp)
        if not token: continue

        for tipo, path in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
            res = requests.get(f"{API_BASE_URL}/v1/financeiro/{path}", 
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "expiration_date_from": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                    "expiration_date_to": d_fim.strftime('%Y-%m-%dT23:59:59Z')
                })
            
            if res.status_code == 200:
                for i in res.json():
                    dt = i.get('due_date') or i.get('expiration_date')
                    dados_totais.append({
                        'Empresa': emp, 'Data': pd.to_datetime(dt[:10]),
                        'Tipo': tipo, 'Valor': float(i.get('value', 0)),
                        'Descrição': i.get('description', 'S/D')
                    })
    
    if dados_totais:
        df = pd.DataFrame(dados_totais)
        st.metric("Saldo Geral", f"R$ {df[df['Tipo']=='Receber']['Valor'].sum() - df[df['Tipo']=='Pagar']['Valor'].sum():,.2f}")
        st.dataframe(df.sort_values('Data'), use_container_width=True)
    else:
        st.info("Nenhum dado encontrado.")
