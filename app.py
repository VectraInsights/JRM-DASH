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
        else:
            st.error(f"Erro Token {empresa}: {response.text}")
            return None
    except Exception as e:
        st.error(f"Falha na renovação: {e}")
        return None

def buscar_financeiro_v2(token, tipo_evento):
    """tipo_evento: 'contas-a-pagar' ou 'contas-a-receber'"""
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Filtro expandido: 30 dias atrás até 90 dias no futuro para garantir captura
    hoje = datetime.now()
    params = {
        "data_vencimento_inicio": (hoje - timedelta(days=30)).strftime("%Y-%m-%d"),
        "data_vencimento_fim": (hoje + timedelta(days=90)).strftime("%Y-%m-%d"),
        "status": "ABERTO"
    }

    try:
        r = requests.get(endpoint, headers=headers, params=params)
        if r.status_code == 200:
            dados = r.json()
            
            # DEBUG: Mostra a estrutura se vier vazio
            if not dados or (isinstance(dados, dict) and not dados.get("items")):
                with st.expander(f"🔍 Investigando resposta vazia ({tipo_evento})"):
                    st.write("A API respondeu, mas não há itens. Estrutura recebida:")
                    st.json(dados)
            
            # Tenta extrair a lista de várias formas comuns em APIs
            if isinstance(dados, list): return dados
            if isinstance(dados, dict):
                return dados.get("items", dados.get("data", dados.get("content", [])))
        else:
            st.error(f"Erro API V2 ({tipo_evento}): {r.status_code} - {r.text}")
        return []
    except Exception as e:
        st.error(f"Erro na chamada V2: {e}")
        return []

# --- INTERFACE PRINCIPAL ---
st.set_page_config(page_title="Dashboard JRM V2", layout="wide")
st.title("📅 Fluxo de Caixa Consolidado (API V2)")

if st.button('🚀 Sincronizar Tudo'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    with st.status("Sincronizando...", expanded=True) as status:
        for row in linhas:
            emp = row['empresa']
            st.write(f"🏢 Conectando à unidade: **{emp}**")
            
            token = obter_access_token(emp, row['refresh_token'], aba)
            
            if token:
                # Busca as duas pontas do financeiro
                pagar = buscar_financeiro_v2(token, "contas-a-pagar")
                receber = buscar_financeiro_v2(token, "contas-a-receber")

                for i in pagar:
                    i.update({'tipo': 'Pagar', 'unidade': emp})
                    consolidado.append(i)
                for i in receber:
                    i.update({'tipo': 'Receber', 'unidade': emp})
                    consolidado.append(i)
                
                st.success(f"✅ {emp}: {len(pagar)} pagamentos e {len(receber)} recebimentos.")
            else:
                st.warning(f"⚠️ {emp}: Não foi possível renovar o acesso.")

        status.update(label="Sincronização Concluída!", state="complete")

    if consolidado:
        st.divider()
        df = pd.DataFrame(consolidado)
        
        # Mapeamento de colunas da V2 (ajustado para os nomes comuns da API Nova)
        # Se a API usar nomes diferentes, o DF mostrará todas as colunas para conferirmos
        st.subheader("📋 Lançamentos Identificados")
        
        # Tratamento de valores para garantir que o cálculo funcione
        def extrair_valor(row):
            return row.get('valor_total', row.get('valor', row.get('amount', 0)))

        df['valor_numerico'] = df.apply(extrair_valor, axis=1)
        
        # Exibição de Métricas
        c1, c2 = st.columns(2)
        rec = df[df['tipo'] == 'Receber']['valor_numerico'].sum()
        pag = df[df['tipo'] == 'Pagar']['valor_numerico'].sum()
        
        c1.metric("Total a Receber", f"R$ {rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {pag:,.2f}")
        
        st.dataframe(df, use_container_width=True)
    else:
        st.error("❌ Nenhum dado encontrado. Verifique os painéis de 'Investigação' acima.")
