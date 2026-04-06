import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES GERAIS ---
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit?gid=0#gid=0"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    """Conecta ao Google Sheets garantindo a formatação PEM correta."""
    try:
        # 1. Carrega os dados do Secrets
        info = dict(st.secrets["connections"]["gsheets"])
        
        # 2. Tratamento da Private Key para evitar erro de PEM
        pk = info["private_key"].strip()
        
        # Garante que o cabeçalho tenha quebra de linha
        if "-----BEGIN PRIVATE KEY-----" in pk and not pk.startswith("-----BEGIN PRIVATE KEY-----\n"):
            pk = pk.replace("-----BEGIN PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\n")
        
        if "-----END PRIVATE KEY-----" in pk and "\n-----END PRIVATE KEY-----" not in pk:
            pk = pk.replace("-----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----")
            
        # Converte caracteres \n literais em quebras reais
        pk = pk.replace("\\n", "\n")
        info["private_key"] = pk
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_url(URL_PLANILHA).sheet1
        
    except Exception as e:
        st.error(f"❌ Erro na Conexão Google: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    """Renova o token na Conta Azul e atualiza a planilha."""
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            
            # Atualiza na planilha (Procura na Coluna A, muda na Coluna B)
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            
            return dados.get("access_token")
        return None
    except:
        return None

def listar_lancamentos(access_token):
    """Busca transações financeiras."""
    url = "https://api.contaazul.com/v1/financials/transactions"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "expiration_start": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "expiration_end": datetime.now().date().isoformat()
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
st.set_page_config(page_title="Dashboard BPO", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    aba = conectar_google_sheets()
    
    with st.status("Sincronizando...", expanded=True) as status:
        try:
            df_tokens = pd.DataFrame(aba.get_all_records())
        except Exception as e:
            st.error(f"Erro ao ler a planilha: {e}")
            st.stop()

        todos_dados = []
        for i, row in df_tokens.iterrows():
            empresa = row['empresa']
            st.write(f"Processando: {empresa}...")
            
            acc_token = obter_access_token(empresa, row['refresh_token'], aba)
            if acc_token:
                importados = listar_lancamentos(acc_token)
                for item in importados:
                    item['origem_empresa'] = empresa
                    item['valor_total'] = float(item.get('value', 0))
                todos_dados.extend(importados)
        
        status.update(label="Sincronização concluída!", state="complete")

    if todos_dados:
        st.dataframe(pd.DataFrame(todos_dados), use_container_width=True)
    else:
        st.error("Nenhum dado coletado. Verifique os tokens.")
