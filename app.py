import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit?gid=0#gid=0"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    """Conecta ao Sheets reconstruindo a chave PEM para evitar erros de byte."""
    try:
        info = dict(st.secrets["connections"]["gsheets"])
        
        # RECONSTRUÇÃO DA CHAVE: Remove tudo e mantém só o código Base64
        raw_key = info["private_key"]
        miolo = raw_key.replace("-----BEGIN PRIVATE KEY-----", "")
        miolo = miolo.replace("-----END PRIVATE KEY-----", "")
        miolo = miolo.replace("\\n", "").replace("\n", "").strip().strip("'").strip('"')
        
        # Monta o PEM oficial com quebras de linha reais
        info["private_key"] = f"-----BEGIN PRIVATE KEY-----\n{miolo}\n-----END PRIVATE KEY-----\n"
        
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
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
            # Atualiza na planilha (Empresa na Col A, Token na Col B)
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        return None
    except:
        return None

def listar_lancamentos(access_token):
    """Busca transações financeiras dos últimos 30 dias."""
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
st.set_page_config(page_title="Dashboard BPO JRM", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    aba = conectar_google_sheets()
    
    with st.status("Coletando dados...", expanded=True) as status:
        try:
            df_tokens = pd.DataFrame(aba.get_all_records())
        except Exception as e:
            st.error(f"Erro ao ler a planilha: {e}")
            st.stop()

        todos_dados = []
        for i, row in df_tokens.iterrows():
            empresa = row['empresa']
            st.write(f"Processando: **{empresa}**...")
            
            acc_token = obter_access_token(empresa, row['refresh_token'], aba)
            if acc_token:
                importados = listar_lancamentos(acc_token)
                for item in importados:
                    item['origem_empresa'] = empresa
                    item['valor'] = float(item.get('value', 0))
                todos_dados.extend(importados)
            else:
                st.warning(f"⚠️ {empresa}: Token inválido.")
        
        status.update(label="Sincronização concluída!", state="complete", expanded=False)

    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ {len(df_final)} lançamentos importados.")
        st.dataframe(df_final, use_container_width=True)
    else:
        st.error("Nenhum dado coletado.")
else:
    st.info("Clique no botão para iniciar.")
