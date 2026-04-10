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

# Credenciais e Endpoints atualizados
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]

AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api-v2.contaazul.com"
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

# --- SIDEBAR: CONEXÃO E FILTROS ---

with st.sidebar:
    st.header("🔗 Conexão Conta Azul")
    params_auth = f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
    url_final = AUTH_URL + params_auth
    st.link_button("Vincular Nova Empresa", url_final, type="primary", use_container_width=True)
    
    st.divider()
    
    st.header("📊 Filtros")
    sh = get_sheet()
    lista_empresas = []
    if sh:
        df_sheet = pd.DataFrame(sh.get_all_records())
        lista_empresas = df_sheet['empresa'].unique().tolist() if not df_sheet.empty else []

    sel_empresa = st.selectbox("Selecione a Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("De", datetime.now() - timedelta(days=7))
    d_fim = st.date_input("Até", datetime.now() + timedelta(days=30))

# --- LÓGICA DE CALLBACK (NOVO VÍNCULO) ---

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
                    data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})
                
                if res.status_code == 200:
                    data = res.json()
                    update_refresh_token(nome_nova_empresa, data['refresh_token'])
                    st.success(f"Empresa '{nome_nova_empresa}' vinculada!")
                    st.query_params.clear() 
                    st.rerun()
                else:
                    st.error(f"Erro na troca do token: {res.text}")

# --- ÁREA PRINCIPAL: PROCESSAMENTO E DASHBOARD ---

if st.button("🚀 Sincronizar Dados", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados = []
    
    for emp in alvos:
        with st.status(f"Buscando dados de: {emp}...", expanded=False) as status:
            token = get_access_token(emp)
            
            if not token: 
                st.error(f"❌ Erro de Conexão: A empresa '{emp}' precisa de novo vínculo.")
                continue

            # Usando EXATAMENTE os endpoints que você forneceu
            for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
                url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
                
                # Ajuste de data para o formato simples YYYY-MM-DD
                # Muitas vezes o erro 404 ocorre quando o parâmetro vai com caracteres inválidos
                res = requests.get(
                    url, 
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "expiration_date_from": d_inicio.strftime('%Y-%m-%d'),
                        "expiration_date_to": d_fim.strftime('%Y-%m-%d')
                    }
                )
                
                if res.status_code == 200:
                    lista_retorno = res.json()
                    # A API costuma retornar uma lista direta ou um dicionário com 'items'
                    # Se vier como lista:
                    itens = lista_retorno if isinstance(lista_retorno, list) else lista_retorno.get('items', [])
                    
                    for i in itens:
                        dt = i.get('due_date') or i.get('expiration_date')
                        if dt:
                            dados.append({
                                'Empresa': emp, 
                                'Data': pd.to_datetime(dt[:10]),
                                'Tipo': tipo, 
                                'Valor': float(i.get('value', 0)),
                                'Descrição': i.get('description', 'S/D')
                            })
                else:
                    # Se der 404 aqui, vamos ver a URL completa gerada para debugar
                    st.error(f"Erro {res.status_code} em {emp} ({tipo})")
                    st.code(f"URL tentada: {res.url}") 
            
            status.update(label=f"Dados de {emp} processados!", state="complete")

    if dados:
        df_final = pd.DataFrame(dados)
        
        # Resumo em Cards
        c1, c2, c3 = st.columns(3)
        rec = df_final[df_final['Tipo'] == 'Receber']['Valor'].sum()
        pag = df_final[df_final['Tipo'] == 'Pagar']['Valor'].sum()
        
        c1.metric("Total a Receber", f"R$ {rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo Líquido", f"R$ {(rec - pag):,.2f}")
        
        st.divider()
        
        # Tabela formatada
        st.dataframe(
            df_final.sort_values('Data'), 
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "Data": st.column_config.DateColumn(format="DD/MM/YYYY")
            }
        )
    else:
        st.info("Nenhum lançamento encontrado para os filtros aplicados.")
