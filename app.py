import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- CARREGAMENTO DOS SECRETS ---
try:
    # Usamos .strip() para remover qualquer espaço acidental
    C_ID = st.secrets["api"]["client_id"].strip()
    C_SECRET = st.secrets["api"]["client_secret"].strip()
    
    # Se não achar o refresh_token, o app avisa antes de dar erro
    if "refresh_token" in st.secrets["api"]:
        R_TOKEN_INI = st.secrets["api"]["refresh_token"].strip()
    else:
        st.error("⚠️ O campo 'refresh_token' está faltando na seção [api] dos seus Secrets.")
        st.stop()
except KeyError as e:
    st.error(f"❌ Chave não encontrada nos Secrets: {e}. Verifique se a seção se chama [api].")
    st.stop()

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Dashboard JRM", layout="wide")

def realizar_refresh():
    """Tenta renovar o acesso usando as credenciais do Secrets"""
    url = "https://api.contaazul.com/oauth2/token"
    
    # Prioriza o refresh token da sessão (que é o mais novo)
    token_atual = st.session_state.get('refresh_token', R_TOKEN_INI)
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": token_atual
    }

    try:
        # Enviando ID e SECRET via Basic Auth (padrão Conta Azul)
        response = requests.post(url, data=payload, auth=(C_ID, C_SECRET))
        
        if response.status_code == 200:
            dados = response.json()
            st.session_state.access_token = dados.get("access_token")
            st.session_state.refresh_token = dados.get("refresh_token")
            return True
        else:
            # Caso falhe, mostra o erro técnico da API
            erro_detalhado = response.text
            st.error(f"Falha na Autenticação (Status {response.status_code}): {erro_detalhado}")
            return False
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return False

def consultar_v1(endpoint, d1, d2):
    """Busca dados de Contas a Pagar/Receber"""
    if 'access_token' not in st.session_state:
        if not realizar_refresh(): return []

    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    headers = {"Authorization": f"Bearer {st.session_state.access_token}"}
    params = {"data_vencimento_de": d1, "data_vencimento_ate": d2, "size": 100}

    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 401:
        if realizar_refresh():
            headers["Authorization"] = f"Bearer {st.session_state.access_token}"
            res = requests.get(url, headers=headers, params=params)
            
    return res.json() if res.status_code == 200 else []

# --- INTERFACE ---
st.title("📊 Painel Financeiro - Contas JRM")

with st.sidebar:
    st.header("Filtros")
    data_inicio = st.date_input("Início", datetime(2026, 4, 1))
    data_fim = st.date_input("Fim", datetime(2026, 4, 30))
    botao = st.button("Sincronizar com Conta Azul")

if botao:
    with st.spinner("Processando..."):
        r = consultar_v1("contas-a-receber", data_inicio, data_fim)
        p = consultar_v1("contas-a-pagar", data_inicio, data_fim)

        if r or p:
            df_r = pd.DataFrame(r)
            df_p = pd.DataFrame(p)
            
            # Cards de resumo
            c1, c2, c3 = st.columns(3)
            val_r = df_r['value'].sum() if not df_r.empty else 0
            val_p = df_p['value'].sum() if not df_p.empty else 0
            
            c1.metric("A Receber", f"R$ {val_r:,.2f}")
            c2.metric("A Pagar", f"R$ {val_p:,.2f}", delta_color="inverse")
            c3.metric("Saldo", f"R$ {val_r - val_p:,.2f}")
            
            st.divider()
            t_rec, t_pag = st.tabs(["📥 Receitas", "📤 Despesas"])
            with t_rec: st.dataframe(df_r, use_container_width=True)
            with t_pag: st.dataframe(df_p, use_container_width=True)
        else:
            st.warning("Nenhum dado encontrado ou erro de acesso.")
