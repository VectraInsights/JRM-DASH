import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES DE AMBIENTE ---
st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# Credenciais (Devem estar no seu .streamlit/secrets.toml)
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]

TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api.contaazul.com"

# --- INFRAESTRUTURA DE DADOS ---

def get_sheet():
    """Conecta à planilha que armazena os tokens das empresas."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        # Substitua pela sua URL de planilha real
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro de conexão com Google Sheets: {e}")
        return None

def update_tokens_in_sheet(empresa, novo_rt):
    """Atualiza o Refresh Token na planilha para evitar o erro 401 no próximo acesso."""
    sh = get_sheet()
    if not sh: return
    try:
        cell = sh.find(empresa)
        sh.update_cell(cell.row, 2, novo_rt)
    except:
        # Se a empresa não existir, cria uma nova linha
        sh.append_row([empresa, novo_rt])

def get_valid_access_token(empresa_nome):
    """Executa o POST de renovação exatamente como você descreveu."""
    sh = get_sheet()
    if not sh: return None
    
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
    except:
        st.error(f"Empresa '{empresa_nome}' não encontrada na base de dados.")
        return None

    # Codificação Base64 das credenciais para o Header Basic
    auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_b64 = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": rt_atual
    }
    
    res = requests.post(TOKEN_URL, headers=headers, data=payload)

    if res.status_code == 200:
        dados_auth = res.json()
        # PASSO CRÍTICO: Salvar o NOVO refresh_token imediatamente
        update_tokens_in_sheet(empresa_nome, dados_auth['refresh_token'])
        return dados_auth['access_token']
    else:
        st.error(f"Falha crítica na renovação para {empresa_nome}. Status: {res.status_code}")
        st.json(res.json())
        return None

# --- INTERFACE E PROCESSAMENTO ---

with st.sidebar:
    st.header("⚙️ Configurações")
    sh = get_sheet()
    lista_empresas = pd.DataFrame(sh.get_all_records())['empresa'].unique().tolist() if sh else []
    sel_empresa = st.selectbox("Selecione a Empresa", ["TODAS"] + lista_empresas)
    
    d_inicio = st.date_input("Data Início", datetime.now() - timedelta(days=7))
    d_fim = st.date_input("Data Fim", datetime.now() + timedelta(days=30))

if st.button("🚀 Sincronizar Dashboard", type="primary", use_container_width=True):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados_consolidados = []
    
    for emp in alvos:
        with st.status(f"Autenticando {emp}...", expanded=False) as status:
            token = get_valid_access_token(emp)
            if not token: continue
            
            # Busca Receitas e Despesas
            for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
                url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
                params = {
                    "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
                    "data_vencimento_ate": d_fim.strftime('%Y-%m-%d')
                }
                
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
                
                # Depurador técnico embutido
                with st.expander(f"Inspecionar {emp} - {tipo}"):
                    st.write(f"Status: {res.status_code}")
                    st.json(res.json())

                if res.status_code == 200:
                    itens = res.json().get('itens', [])
                    for i in itens:
                        dados_consolidados.append({
                            'Empresa': emp,
                            'Data': i.get('data_vencimento')[:10],
                            'Tipo': tipo,
                            'Valor': float(i.get('valor', 0)),
                            'Descrição': i.get('descricao', 'S/D'),
                            'Pago': "Sim" if i.get('pago') else "Não"
                        })
            status.update(label=f"Dados de {emp} capturados!", state="complete")

    if dados_consolidados:
        df = pd.DataFrame(dados_consolidados)
        
        # Resumo em Cards
        c1, c2, c3 = st.columns(3)
        rec = df[df['Tipo'] == 'Receber']['Valor'].sum()
        pag = df[df['Tipo'] == 'Pagar']['Valor'].sum()
        
        c1.metric("Total a Receber", f"R$ {rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo do Período", f"R$ {(rec - pag):,.2f}")
        
        st.divider()
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Nenhum dado financeiro encontrado para os filtros aplicados.")
