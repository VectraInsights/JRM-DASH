import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    try:
        gs = st.secrets["connections"]["gsheets"]
        info = {
            "type": gs["type"],
            "project_id": gs["project_id"],
            "private_key_id": gs["private_key_id"],
            "client_email": gs["client_email"],
            "client_id": gs["client_id"],
            "auth_uri": gs["auth_uri"],
            "token_uri": gs["token_uri"],
            "auth_provider_x509_cert_url": gs["auth_provider_x509_cert_url"],
            "client_x509_cert_url": gs["client_x509_cert_url"]
        }
        b64_key = gs["private_key_base64"]
        key_decoded = base64.b64decode(b64_key).decode("utf-8")
        info["private_key"] = key_decoded.replace("\\n", "\n")

        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(ID_PLANILHA)
        return spreadsheet.worksheet("Página1")
    except Exception as e:
        st.error(f"❌ Falha técnica na conexão: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        else:
            st.error(f"❌ Erro de Token ({empresa}): {response.json().get('error_description', response.text)}")
            return None
    except:
        return None

def listar_lancamentos_futuros(access_token):
    """Busca contas a pagar e receber dos PRÓXIMOS 30 dias."""
    url = "https://api.contaazul.com/v1/financials/transactions"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # AJUSTE DO PERÍODO: De hoje até +30 dias
    data_inicio = datetime.now().date().isoformat()
    data_fim = (datetime.now() + timedelta(days=30)).date().isoformat()
    
    params = {
        "expiration_start": data_inicio,
        "expiration_end": data_fim,
        "status": "OPEN"  # Traz apenas o que ainda NÃO foi pago/recebido
    }
    
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            res = r.json()
            return res if isinstance(res, list) else res.get('items', [])
        return []
    except:
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard JRM - Futuro", layout="wide")
st.title("📅 Projeção de Recebíveis/Pagáveis (Próximos 30 dias)")

if st.button('🚀 Gerar Projeção Financeira'):
    aba = conectar_google_sheets()
    
    with st.status("Sincronizando com as APIs...", expanded=True) as status:
        lista_dados = aba.get_all_records()
        todos_lancamentos = []
        
        for row in lista_dados:
            emp = row['empresa']
            token_ref = row['refresh_token']
            
            st.write(f"🔍 Analisando Futuro de: **{emp}**")
            
            acc_token = obter_access_token(emp, token_ref, aba)
            if acc_token:
                itens = listar_lancamentos_futuros(acc_token)
                for i in itens:
                    i['unidade'] = emp
                    # Identificar se é Entrada ou Saída
                    i['tipo'] = 'Recebível' if i.get('category_group') == 'REVENUE' else 'Pagável'
                todos_lancamentos.extend(itens)
        
        status.update(label="Análise Concluída!", state="complete")

    if todos_lancamentos:
        df = pd.DataFrame(todos_lancamentos)
        
        # Formatação básica para visualização
        col1, col2 = st.columns(2)
        receita = df[df['tipo'] == 'Recebível']['value'].sum()
        despesa = df[df['tipo'] == 'Pagável']['value'].sum()
        
        col1.metric("Total a Receber", f"R$ {receita:,.2f}")
        col2.metric("Total a Pagar", f"R$ {despesa:,.2f}")

        st.subheader("Detalhamento dos Próximos 30 Dias")
        st.dataframe(df[['due_date', 'description', 'value', 'tipo', 'unidade']], use_container_width=True)
    else:
        st.info("Nenhum lançamento em aberto encontrado para os próximos 30 dias.")
