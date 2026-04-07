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
    Filtra apenas os próximos 30 dias a partir de HOJE.
    """
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # REGRA: A vencer (Hoje até +30 dias)
    hoje = datetime.now()
    data_inicio = hoje.strftime("%Y-%m-%d")
    data_fim = (hoje + timedelta(days=30)).strftime("%Y-%m-%d")

    params = {
        "pagina": 1,
        "tamanho_pagina": 1000,
        "data_vencimento_de": data_inicio,
        "data_vencimento_ate": data_fim,
        "status": "EM_ABERTO"
    }

    try:
        r = requests.get(endpoint, headers=headers, params=params)
        if r.status_code == 200:
            return r.json().get("itens", [])
        return []
    except:
        return []

# --- INTERFACE ---
st.set_page_config(page_title="Fluxo 30 Dias", layout="wide")
st.title("📅 Projeção de Fluxo (Próximos 30 Dias)")

if st.button('🚀 Sincronizar Janela de 30 Dias'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    with st.status("Filtrando lançamentos futuros...", expanded=True) as status:
        for row in linhas:
            emp = row['empresa']
            token = obter_access_token(emp, row['refresh_token'], aba)
            
            if token:
                pagar = buscar_financeiro_v2(token, "contas-a-pagar")
                receber = buscar_financeiro_v2(token, "contas-a-receber")

                for i in pagar:
                    i.update({'tipo_jrm': 'Pagar', 'unidade_jrm': emp})
                    consolidado.append(i)
                for i in receber:
                    i.update({'tipo_jrm': 'Receber', 'unidade_jrm': emp})
                    consolidado.append(i)
                
                st.write(f"🏢 **{emp}**: {len(pagar) + len(receber)} títulos para o período.")
            else:
                st.error(f"❌ {emp}: Erro de Token")

    if consolidado:
        df = pd.DataFrame(consolidado)
        df['valor_num'] = df.apply(lambda x: float(x.get('valor', 0)), axis=1)
        
        st.divider()
        c1, c2, c3 = st.columns(3)
        total_rec = df[df['tipo_jrm'] == 'Receber']['valor_num'].sum()
        total_pag = df[df['tipo_jrm'] == 'Pagar']['valor_num'].sum()
        
        c1.metric("Recebimentos (30d)", f"R$ {total_rec:,.2f}")
        c2.metric("Pagamentos (30d)", f"R$ {total_pag:,.2f}")
        c3.metric("Saldo do Período", f"R$ {(total_rec - total_pag):,.2f}")

        # Tabela ordenada por data mais próxima
        st.subheader(f"📋 Próximos Vencimentos (até {(datetime.now()+timedelta(days=30)).strftime('%d/%m/%Y')})")
        cols = ['data_vencimento', 'descricao', 'valor_num', 'tipo_jrm', 'unidade_jrm']
        st.dataframe(df[cols].sort_values('data_vencimento'), use_container_width=True)
    else:
        st.info("Nenhum lançamento encontrado com vencimento nos próximos 30 dias.")
