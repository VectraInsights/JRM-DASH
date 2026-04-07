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
        st.error(f"Erro Google: {e}"); st.stop()

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
            "grant_type": "refresh_token",
            "refresh_token": str(refresh_token_raw).strip()
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
    Conforme documentação: página e tamanho_pagina são OBRIGATÓRIOS.
    """
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    hoje = datetime.now()
    params = {
        "pagina": 1,
        "tamanho_pagina": 1000, # Maximizando para pegar tudo de uma vez
        "data_vencimento_de": "2023-01-01",
        "data_vencimento_ate": (hoje + timedelta(days=90)).strftime("%Y-%m-%d"),
        # Status deve ser passado como lista ou string única conforme o caso
        "status": "EM_ABERTO" 
    }

    try:
        r = requests.get(endpoint, headers=headers, params=params)
        if r.status_code == 200:
            dados = r.json()
            # Conforme doc: a lista correta está na chave 'itens'
            return dados.get("itens", [])
        else:
            st.error(f"Erro {r.status_code} na JTL ({tipo_evento}): {r.text}")
            return []
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard Financeiro", layout="wide")
st.title("📊 Fluxo de Caixa JRM (API V2)")

if st.button('🚀 Sincronizar com Conta Azul'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    with st.status("Extraindo dados financeiros...", expanded=True) as status:
        for row in linhas:
            emp = row['empresa']
            token = obter_access_token(emp, row['refresh_token'], aba)
            
            if token:
                # Busca Pagar e Receber
                pagar = buscar_financeiro_v2(token, "contas-a-pagar")
                receber = buscar_financeiro_v2(token, "contas-a-receber")

                for i in pagar:
                    i.update({'tipo_jrm': 'Pagar', 'unidade_jrm': emp})
                    consolidado.append(i)
                for i in receber:
                    i.update({'tipo_jrm': 'Receber', 'unidade_jrm': emp})
                    consolidado.append(i)
                
                st.success(f"✅ {emp}: {len(pagar) + len(receber)} registros.")
            else:
                st.error(f"❌ {emp}: Falha na autenticação.")

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # Na V2, o valor geralmente vem em 'valor' ou dentro de 'valor_total'
        def tratar_valor(row):
            return float(row.get('valor', 0))

        df['valor_num'] = df.apply(tratar_valor, axis=1)
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        total_rec = df[df['tipo_jrm'] == 'Receber']['valor_num'].sum()
        total_pag = df[df['tipo_jrm'] == 'Pagar']['valor_num'].sum()
        
        c1.metric("A Receber (Total)", f"R$ {total_rec:,.2f}")
        c2.metric("A Pagar (Total)", f"R$ {total_pag:,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(total_rec - total_pag):,.2f}")

        # Exibição da tabela conforme colunas da documentação
        st.subheader("📋 Detalhamento dos Lançamentos")
        colunas_doc = ['data_vencimento', 'descricao', 'valor_num', 'tipo_jrm', 'unidade_jrm']
        st.dataframe(df[colunas_doc].sort_values('data_vencimento'), use_container_width=True)
    else:
        st.warning("Nenhum dado encontrado para os filtros aplicados.")
