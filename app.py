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
URL_BASE_V2 = "https://api-v2.contaazul.com"

# --- CONEXÃO GOOGLE (MANTIDA) ---
def conectar_google_sheets():
    try:
        gs = st.secrets["connections"]["gsheets"]
        info = {
            "type": gs["type"], "project_id": gs["project_id"], "private_key_id": gs["private_key_id"],
            "client_email": gs["client_email"], "client_id": gs["client_id"], "auth_uri": gs["auth_uri"],
            "token_uri": gs["token_uri"], "auth_provider_x509_cert_url": gs["auth_provider_x509_cert_url"],
            "client_x509_cert_url": gs["client_x509_cert_url"]
        }
        b64_key = gs["private_key_base64"]
        info["private_key"] = base64.b64decode(b64_key).decode("utf-8").replace("\\n", "\n")
        creds = Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
        return gspread.authorize(creds).open_by_key(ID_PLANILHA).worksheet("Página1")
    except Exception as e:
        st.error(f"Erro Google: {e}"); st.stop()

# --- AUTENTICAÇÃO (ADAPTADA) ---
def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": str(refresh_token_raw).strip()
    }
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            if novo_refresh:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        return None
    except: return None

# --- BUSCA DE DADOS (NOVO PADRÃO V2) ---
def buscar_financeiro_v2(token, tipo_evento):
    """tipo_evento deve ser 'contas-a-pagar' ou 'contas-a-receber'"""
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {"Authorization": f"Bearer {token}"}
    
    # Filtro: Próximos 45 dias
    data_fim = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
    params = {"data_vencimento_fim": data_fim}

    try:
        r = requests.get(endpoint, headers=headers, params=params)
        if r.status_code == 200:
            # A V2 costuma retornar um objeto com uma lista dentro, ex: {"items": [...]}
            dados = r.json()
            return dados.get("items", []) if isinstance(dados, dict) else dados
        return []
    except: return []

# --- INTERFACE ---
st.title("📊 Fluxo Consolidado - API V2")

if st.button('🚀 Sincronizar V2'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        with st.expander(f"Processando {emp}", expanded=False):
            token = obter_access_token(emp, row['refresh_token'], aba)
            
            if token:
                # Busca Pagar e Receber separadamente na V2
                pagar = buscar_financeiro_v2(token, "contas-a-pagar")
                receber = buscar_financeiro_v2(token, "contas-a-receber")

                for item in pagar:
                    item.update({'tipo': 'Pagar', 'unidade': emp})
                    consolidado.append(item)
                for item in receber:
                    item.update({'tipo': 'Receber', 'unidade': emp})
                    consolidado.append(item)
                
                st.success(f"{len(pagar) + len(receber)} registros encontrados.")
            else:
                st.error("Falha na renovação do token.")

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # Ajuste de colunas conforme o novo JSON da V2
        # Na V2 as colunas costumam ser 'data_vencimento' e 'valor' ou 'valor_total'
        st.divider()
        st.subheader("Resultados Consolidados")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Nenhum dado encontrado nos novos endpoints.")
