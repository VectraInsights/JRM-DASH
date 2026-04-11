import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES DE AMBIENTE ---
st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# Configurações de API (Centralizadas)
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]

AUTH_URL = "https://auth.contaazul.com/login"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api.contaazul.com" 
SCOPE = "openid+profile+aws.cognito.signin.user.admin"

# --- FUNÇÕES DE INFRAESTRUTURA ---

def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na planilha: {e}")
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

# --- SIDEBAR E OAuth ---

with st.sidebar:
    st.header("🔗 Gestão de Acesso")
    url_auth = f"{AUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope={SCOPE}"
    st.link_button("Vincular Nova Empresa", url_auth, type="primary", use_container_width=True)
    
    # Captura do Code (Retorno do OAuth)
    query_params = st.query_params
    if "code" in query_params:
        with st.expander("✨ Finalizar Vínculo", expanded=True):
            nome_emp = st.text_input("Nome da Empresa")
            if st.button("Salvar Vínculo"):
                auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                res = requests.post(TOKEN_URL, 
                    headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"},
                    data={"grant_type": "authorization_code", "code": query_params["code"], "redirect_uri": REDIRECT_URI})
                if res.status_code == 200:
                    update_refresh_token(nome_emp, res.json()['refresh_token'])
                    st.success("Vinculado! Limpando URL...")
                    st.query_params.clear()
                    st.rerun()
    
    st.divider()
    st.header("📊 Filtros de Visualização")
    sh = get_sheet()
    lista_empresas = pd.DataFrame(sh.get_all_records())['empresa'].unique().tolist() if sh else []
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("Início", datetime.now() - timedelta(days=7))
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=30))

# --- PROCESSAMENTO DOS DADOS ---

if st.button("🚀 Sincronizar e Atualizar Dashboard", type="primary", use_container_width=True):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados = []
    
    for emp in alvos:
        with st.status(f"Lendo {emp}...", expanded=False) as status:
            token = get_access_token(emp)
            if not token: continue

            for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
                url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
                params = {
                    "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
                    "data_vencimento_ate": d_fim.strftime('%Y-%m-%d')
                }
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)

                # --- DEPURADOR DE RESPOSTA ---
                with st.expander(f"🔍 Depurador: {emp} ({tipo})", expanded=False):
                    st.write(f"URL: {res.url}")
                    st.write(f"Status: {res.status_code}")
                    st.json(res.json()) 

                if res.status_code == 200:
                    corpo = res.json()
                    # Garante que 'itens' existe e é uma lista
                    itens = corpo.get('itens', [])
                    
                    for i in itens:
                        # Fallback de campos: tenta v1 e variações comuns
                        venc = i.get('data_vencimento') or i.get('due_date')
                        val = i.get('valor') or i.get('value') or i.get('valor_liquido_total')
                        desc = i.get('descricao') or i.get('description') or 'S/D'
                        
                        if venc and val is not None:
                            dados.append({
                                'Empresa': emp,
                                'Data': pd.to_datetime(venc[:10]),
                                'Tipo': tipo,
                                'Valor': float(val),
                                'Descrição': desc,
                                'Status': 'Pago' if i.get('pago') or i.get('status') == 'PAID' else 'Pendente'
                            })
            status.update(label=f"Check: {emp} OK", state="complete")

    if dados:
        df = pd.DataFrame(dados)
    else:
        st.warning("⚠️ A API retornou 200 (OK), mas a lista de 'itens' veio vazia.")
        st.info("Verifique no depurador acima se os campos no JSON são realmente 'data_vencimento' e 'valor'.")
        
        # --- CARDS DE RESUMO ---
        rec = df[df['Tipo'] == 'Receber']['Valor'].sum()
        pag = df[df['Tipo'] == 'Pagar']['Valor'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("A Receber", f"R$ {rec:,.2f}")
        c2.metric("A Pagar", f"R$ {pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo Previsto", f"R$ {(rec - pag):,.2f}")
        
        st.divider()
        
        # --- TABELA DE LANÇAMENTOS ---
        st.subheader("📋 Detalhamento de Títulos")
        st.dataframe(
            df.sort_values('Data'),
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "Data": st.column_config.DateColumn(format="DD/MM/YYYY"),
                "Tipo": st.column_config.TextColumn(help="Receita ou Despesa")
            }
        )
    else:
        st.warning("Nenhum dado encontrado para este período.")
