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
        st.error(f"❌ Falha técnica na conexão Google: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    # Adicionando um log para conferir se estamos enviando algo vazio
    if not refresh_token:
        st.error(f"❌ Erro: Refresh Token da {empresa} está vazio na planilha!")
        return None
        
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Salva IMEDIATAMENTE na planilha para não perder a sincronia
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        else:
            # Se der erro aqui, precisamos ver o que a Conta Azul diz
            st.error(f"❌ Falha ao renovar para {empresa}: {response.text}")
            return None
    except Exception as e:
        st.error(f"❌ Erro de conexão com Conta Azul: {e}")
        return None

def listar_lancamentos_futuros(access_token, empresa_nome):
    """Busca lançamentos e exibe depuração bruta na tela."""
    url = "https://api.contaazul.com/v1/financials/transactions"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Range ampliado para garantir que pegamos o que você está vendo
    # De 7 dias atrás até 45 dias no futuro
    data_inicio = (datetime.now() - timedelta(days=7)).date().isoformat()
    data_fim = (datetime.now() + timedelta(days=45)).date().isoformat()
    
    params = {
        "expiration_start": data_inicio,
        "expiration_end": data_fim
        # "status": "OPEN" # Removido para depuração total
    }
    
    try:
        st.info(f"📡 Chamando API para {empresa_nome}...")
        st.write(f"Período: {data_inicio} até {data_fim}")
        
        r = requests.get(url, headers=headers, params=params)
        
        if r.status_code == 200:
            res_bruto = r.json()
            # Se for uma lista direta ou um dicionário com 'items'
            itens = res_bruto if isinstance(res_bruto, list) else res_bruto.get('items', [])
            
            # --- DEPURAÇÃO VISUAL ---
            with st.expander(f"DEBUG: Dados Brutos - {empresa_nome}"):
                st.write(f"Total de itens retornados: {len(itens)}")
                st.json(res_bruto) # Mostra o JSON bonitinho para análise
            
            return itens
        else:
            st.error(f"Erro {r.status_code} na API {empresa_nome}: {r.text}")
            return []
    except Exception as e:
        st.error(f"Falha na requisição {empresa_nome}: {e}")
        return []

# --- INTERFACE ---
st.set_page_config(page_title="DEBUG - Dashboard JRM", layout="wide")
st.title("📅 Depuração de Lançamentos JRM")

if st.button('🚀 Rodar Sincronização com Debug'):
    aba = conectar_google_sheets()
    
    with st.status("Processando...", expanded=True) as status:
        lista_dados = aba.get_all_records()
        todos_lancamentos = []
        
        for row in lista_dados:
            emp = row['empresa']
            token_ref = row['refresh_token']
            
            st.markdown(f"### 🏢 Empresa: {emp}")
            
            acc_token = obter_access_token(emp, token_ref, aba)
            if acc_token:
                itens = listar_lancamentos_futuros(acc_token, emp)
                
                for i in itens:
                    i['unidade'] = emp
                    # Verifica se o campo de valor é 'value' ou 'amount' (depende da versão da API)
                    v = i.get('value') if i.get('value') is not None else i.get('amount', 0)
                    i['valor_ajustado'] = v
                    i['tipo'] = 'Recebível' if i.get('category_group') == 'REVENUE' else 'Pagável'
                
                todos_lancamentos.extend(itens)
            else:
                st.warning(f"Pulei {emp} por falta de token válido.")
        
        status.update(label="Processo Concluído!", state="complete")

    if todos_lancamentos:
        st.divider()
        df = pd.DataFrame(todos_lancamentos)
        
        # Totais
        c1, c2 = st.columns(2)
        receita = df[df['tipo'] == 'Recebível']['valor_ajustado'].sum()
        despesa = df[df['tipo'] == 'Pagável']['valor_ajustado'].sum()
        
        c1.metric("A Receber (No período)", f"R$ {receita:,.2f}")
        c2.metric("A Pagar (No período)", f"R$ {despesa:,.2f}")

        st.subheader("Tabela de Dados Identificados")
        # Mostra as colunas que conseguimos mapear
        colunas_disponiveis = [c for c in ['due_date', 'description', 'valor_ajustado', 'tipo', 'unidade', 'status'] if c in df.columns]
        st.dataframe(df[colunas_disponiveis], use_container_width=True)
    else:
        st.error("❌ Fim da execução: A API não retornou nenhum lançamento para as empresas processadas.")
