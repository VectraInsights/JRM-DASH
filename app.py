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
    """Conecta ao Google Sheets limpando a chave de caracteres parasitas."""
    try:
        # 1. Carrega os dados brutos do Secrets
        info = dict(st.secrets["connections"]["gsheets"])
        
        # 2. Limpeza Profunda (Sanitização)
        # Remove espaços no início/fim e aspas extras que o Streamlit pode inserir
        pk = info["private_key"].strip().strip("'").strip('"')
        
        # Converte o texto "\n" em quebra de linha real (essencial para PEM)
        pk = pk.replace("\\n", "\n")
        
        # Garante que a chave comece exatamente com o cabeçalho correto
        if not pk.startswith("-----BEGIN"):
            # Se houver lixo antes do início, tenta localizar o começo real
            inicio = pk.find("-----BEGIN")
            if inicio != -1:
                pk = pk[inicio:]
        
        info["private_key"] = pk
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_url(URL_PLANILHA).sheet1
        
    except Exception as e:
        st.error(f"❌ Erro na Chave Google: {e}")
        # Mostra os primeiros caracteres para debug visual (com segurança)
        if 'pk' in locals():
            st.code(f"Início da chave detectado: {pk[:40]}...")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    """Renova o token na Conta Azul e salva o novo na planilha."""
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Atualiza a célula ao lado do nome da empresa (Coluna B)
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        return None
    except:
        return None

def listar_lancamentos(access_token):
    """Busca transações dos últimos 30 dias."""
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

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Dashboard BPO Financeiro", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    aba = conectar_google_sheets()
    
    with st.status("Conectando e buscando dados...", expanded=True) as status:
        try:
            dados_planilha = aba.get_all_records()
            df_tokens = pd.DataFrame(dados_planilha)
        except Exception as e:
            st.error(f"Erro ao ler a planilha: {e}")
            st.stop()

        todos_dados = []
        for i, row in df_tokens.iterrows():
            empresa = row['empresa']
            st.write(f"Sincronizando: **{empresa}**...")
            
            acc_token = obter_access_token(empresa, row['refresh_token'], aba)
            if acc_token:
                importados = listar_lancamentos(acc_token)
                for item in importados:
                    item['origem_empresa'] = empresa
                    item['value'] = float(item.get('value', 0))
                todos_dados.extend(importados)
            else:
                st.warning(f"⚠️ {empresa}: Falha no token (verifique a planilha).")
        
        status.update(label="Sincronização concluída!", state="complete", expanded=False)

    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ {len(df_final)} lançamentos importados com sucesso.")
        st.subheader("Extrato Consolidado")
        st.dataframe(df_final, use_container_width=True)
    else:
        st.error("Nenhum dado encontrado. Verifique os Refresh Tokens.")
else:
    st.info("Clique no botão para iniciar a sincronização via Google Sheets.")
