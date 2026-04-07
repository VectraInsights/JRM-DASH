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
        st.error(f"Erro Google Sheets: {e}"); st.stop()

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    refresh_token = str(refresh_token_raw).strip()
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        })
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            if novo_refresh:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        return None
    except: return None

def buscar_financeiro_v2(token, tipo_evento):
    """
    tipo_evento: 'contas-a-pagar' ou 'contas-a-receber'
    """
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    # Definindo datas explicitamente como strings YYYY-MM-DD
    hoje = datetime.now()
    data_de = "2023-01-01"
    data_ate = (hoje + timedelta(days=60)).strftime("%Y-%m-%d")

    # Parâmetros de consulta
    params = {
        "data_vencimento_de": data_de,
        "data_vencimento_ate": data_ate,
        "status": "ABERTO"
    }

    try:
        # Usamos params=params para que o 'requests' monte a URL corretamente: ?data_vencimento_de=...
        r = requests.get(endpoint, headers=headers, params=params)
        
        if r.status_code == 200:
            dados = r.json()
            # Tenta extrair a lista de itens
            if isinstance(dados, list): return dados
            if isinstance(dados, dict):
                return dados.get("items", dados.get("data", dados.get("content", [])))
        else:
            # Se der erro 400 de novo, vamos mostrar os parâmetros enviados para conferir
            st.error(f"Erro {r.status_code} em {tipo_evento}: {r.text}")
            st.info(f"Parâmetros enviados: {params}")
        return []
    except Exception as e:
        st.error(f"Erro na chamada: {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard Financeiro V2", layout="wide")
st.title("📊 Fluxo de Caixa Consolidado (JRM)")

if st.button('🚀 Sincronizar Agora'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    with st.status("Buscando dados...", expanded=True) as status:
        for row in linhas:
            emp = row['empresa']
            token = obter_access_token(emp, row['refresh_token'], aba)
            
            if token:
                pagar = buscar_financeiro_v2(token, "contas-a-pagar")
                receber = buscar_financeiro_v2(token, "contas-a-receber")

                for i in pagar:
                    i.update({'tipo': 'Pagar', 'unidade': emp})
                    consolidado.append(i)
                for i in receber:
                    i.update({'tipo': 'Receber', 'unidade': emp})
                    consolidado.append(i)
                
                st.success(f"✅ {emp}: {len(pagar)} títulos a pagar | {len(receber)} a receber")
            else:
                st.error(f"❌ {emp}: Falha na renovação do Token")

        status.update(label="Sincronização concluída!", state="complete")

    if consolidado:
        st.divider()
        df = pd.DataFrame(consolidado)
        
        # Tratamento de valores para garantir cálculo numérico
        def extrair_valor_numerico(row):
            # A V2 pode retornar 'valor', 'valor_total' ou 'valor_liquido'
            v = row.get('valor_total') or row.get('valor') or row.get('valor_previsto') or 0
            try:
                return float(v)
            except:
                return 0.0

        df['valor_final'] = df.apply(extrair_valor_numerico, axis=1)
        
        # Exibição de Métricas
        c1, c2, c3 = st.columns(3)
        rec_total = df[df['tipo'] == 'Receber']['valor_final'].sum()
        pag_total = df[df['tipo'] == 'Pagar']['valor_final'].sum()
        
        c1.metric("Total a Receber", f"R$ {rec_total:,.2f}")
        c2.metric("Total a Pagar", f"R$ {pag_total:,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(rec_total - pag_total):,.2f}")

        # Tabela Detalhada
        st.subheader("📋 Detalhamento dos Lançamentos")
        # Ajuste de nomes de colunas conforme o JSON da V2 (data_vencimento e descricao)
        cols_display = ['data_vencimento', 'descricao', 'valor_final', 'tipo', 'unidade']
        existentes = [c for c in cols_display if c in df.columns]
        
        st.dataframe(
            df[existentes].sort_values('data_vencimento', ascending=True), 
            use_container_width=True
        )
    else:
        st.warning("A API não retornou nenhum lançamento aberto para o período.")
