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
        # st.status mantém a interface limpa enquanto processa várias empresas
        with st.status(f"Sincronizando: {emp}...", expanded=False) as status:
            token = get_access_token(emp)
            
            if not token: 
                st.error(f"❌ Falha ao renovar acesso para {emp}. Refaça o vínculo.")
                continue

            for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
                url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
                
                # Payload de parâmetros limpo
                params = {
                    "expiration_date_from": d_inicio.strftime('%Y-%m-%d'),
                    "expiration_date_to": d_fim.strftime('%Y-%m-%d')
                }
                
                res = requests.get(
                    url, 
                    headers={"Authorization": f"Bearer {token}"},
                    params=params
                )
                
                if res.status_code == 200:
                    corpo = res.json()
                    
                    # Extração segura: a API v2 coloca os dados em 'items' ou 'itens'
                    # Se não encontrar nenhum, assume que o retorno pode ser a lista direta
                    lista_items = corpo.get('items') or corpo.get('itens') or (corpo if isinstance(corpo, list) else [])
                    
                    for i in lista_items:
                        # Mapeamento de campos flexível (V1 vs V2)
                        vencimento = i.get('due_date') or i.get('expiration_date')
                        valor = i.get('value') or i.get('valor_liquido_total') or 0
                        
                        if vencimento:
                            dados.append({
                                'Empresa': emp, 
                                'Data': pd.to_datetime(vencimento[:10]),
                                'Tipo': tipo, 
                                'Valor': float(valor),
                                'Descrição': i.get('description') or i.get('memo') or 'S/D'
                            })
                else:
                    # Se der 404, mostramos a URL exata para o seu log de auditoria
                    st.warning(f"Aviso {res.status_code} em {emp} ({tipo})")
                    st.caption(f"Endpoint: {res.url}")
            
            status.update(label=f"Concluído: {emp}", state="complete")

    if dados:
        df_final = pd.DataFrame(dados)
        st.success(f"✅ Sincronização concluída: {len(df_final)} lançamentos.")

        # --- EXIBIÇÃO DO DASHBOARD ---
        c1, c2, c3 = st.columns(3)
        total_rec = df_final[df_final['Tipo'] == 'Receber']['Valor'].sum()
        total_pag = df_final[df_final['Tipo'] == 'Pagar']['Valor'].sum()
        
        c1.metric("Total a Receber", f"R$ {total_rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {total_pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo do Período", f"R$ {(total_rec - total_pag):,.2f}")
        
        st.divider()
        st.dataframe(
            df_final.sort_values('Data'), 
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "Data": st.column_config.DateColumn(format="DD/MM/YYYY")
            }
        )
    else:
        st.info("Nenhum dado encontrado com os filtros atuais.")
