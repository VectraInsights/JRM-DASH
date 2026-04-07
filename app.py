import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from gspread_pandas import Spread, Conf

# --- CONFIGURAÇÕES DE ACESSO ---
C_ID = st.secrets["api"]["client_id"].strip()
C_SECRET = st.secrets["api"]["client_secret"].strip()

# Configuração Google (mantendo sua estrutura de secrets)
credenciais_google = {
    "type": st.secrets["connections.gsheets"]["type"],
    "project_id": st.secrets["connections.gsheets"]["project_id"],
    "private_key_id": st.secrets["connections.gsheets"]["private_key_id"],
    "private_key": st.secrets["connections.gsheets"]["private_key_base64"], 
    "client_email": st.secrets["connections.gsheets"]["client_email"],
    "client_id": st.secrets["connections.gsheets"]["client_id"],
    "auth_uri": st.secrets["connections.gsheets"]["auth_uri"],
    "token_uri": st.secrets["connections.gsheets"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["connections.gsheets"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["connections.gsheets"]["client_x509_cert_url"],
}

# --- FUNÇÕES GOOGLE SHEETS ---
def gerenciar_token_planilha(novo_token=None):
    config = Conf(credenciais_google)
    # Usando o nome exato da sua planilha que aparece na imagem
    spread = Spread("Tokens_ContaAzul", config=config) 
    
    if novo_token:
        # Atualiza apenas a célula B2 (onde está o token da JTL)
        spread.update_cells(start="B2", end="B2", vals=[novo_token], sheet="Tokens")
        return novo_token
    else:
        # Lê a aba "Tokens", pegando o valor da célula B2
        df = spread.sheet_to_df(sheet="Tokens", index=None)
        # Retorna o valor da coluna 'refresh_token' da primeira linha
        return df['refresh_token'].iloc[0]

# --- LÓGICA DE REFRESH CONTA AZUL ---
def renovar_acesso():
    url = "https://api.contaazul.com/oauth2/token"
    
    try:
        token_atual = gerenciar_token_planilha()
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": token_atual
        }

        # Autenticação nativa
        response = requests.post(url, data=payload, auth=(C_ID, C_SECRET))
        
        if response.status_code == 200:
            dados = response.json()
            # SALVA O NOVO TOKEN NA PLANILHA
            gerenciar_token_planilha(novo_token=dados.get("refresh_token"))
            st.session_state.access_token = dados.get("access_token")
            return True
        else:
            st.error(f"Erro na renovação: {response.json().get('error_description', response.text)}")
            return False
    except Exception as e:
        st.error(f"Erro ao acessar planilha ou API: {e}")
        return False

# --- BUSCA DE DADOS ---
def buscar_dados(endpoint, d1, d2):
    if 'access_token' not in st.session_state:
        if not renovar_acesso(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {"data_vencimento_de": d1, "data_vencimento_ate": d2, "size": 100}

    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 401:
        if renovar_acesso():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")
st.title("📊 Gestão Financeira JTL")

with st.sidebar:
    st.header("Filtros")
    data_ini = st.date_input("Início", datetime(2026, 4, 1))
    data_fim = st.date_input("Fim", datetime(2026, 4, 30))
    bt = st.button("🚀 Sincronizar Agora")

if bt:
    with st.spinner("Atualizando tokens e buscando dados..."):
        r = buscar_dados("contas-a-receber", data_ini, data_fim)
        p = buscar_dados("contas-a-pagar", data_ini, data_fim)

        if r or p:
            df_r, df_p = pd.DataFrame(r), pd.DataFrame(p)
            c1, c2, c3 = st.columns(3)
            v_r = df_r['value'].sum() if not df_r.empty else 0
            v_p = df_p['value'].sum() if not df_p.empty else 0
            
            c1.metric("Receitas", f"R$ {v_r:,.2f}")
            c2.metric("Despesas", f"R$ {v_p:,.2f}", delta_color="inverse")
            c3.metric("Saldo", f"R$ {v_r - v_p:,.2f}")
            
            st.divider()
            t1, t2 = st.tabs(["Detalhamento Receitas", "Detalhamento Despesas"])
            with t1: st.dataframe(df_r, use_container_width=True)
            with t2: st.dataframe(df_p, use_container_width=True)
        else:
            st.warning("Nenhum dado retornado. Verifique as datas ou a conexão.")
