import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta
from streamlit_gsheets import GSheetsConnection # Adicione esta linha

# --- 1. CONFIGURAÇÕES DOS SEGREDOS ---
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

# --- 2. CONEXÃO COM A PLANILHA ---
conn = st.connection("gsheets", type=GSheetsConnection)

def atualizar_token_na_planilha(df_completo, nome_empresa, novo_token):
    """Salva o novo refresh_token de volta na planilha do Google."""
    df_completo.loc[df_completo['empresa'] == nome_empresa, 'refresh_token'] = novo_token
    conn.update(data=df_completo)

def obter_access_token(nome_empresa, refresh_token, df_completo):
    """Renova o access_token e já atualiza o refresh_token na planilha."""
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # ATUALIZA A PLANILHA NA HORA
            atualizar_token_na_planilha(df_completo, nome_empresa, novo_refresh)
            return dados.get("access_token")
        else:
            st.error(f"Erro {nome_empresa} (Status {response.status_code}): {response.text}")
            return None
    except Exception as e:
        st.error(f"Erro de conexão na {nome_empresa}: {e}")
        return None

def listar_lancamentos(access_token):
    """Busca os lançamentos financeiros da API."""
    url = "https://api.contaazul.com/v1/financials/transactions"
    params = {
        "expiration_start": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "expiration_end": datetime.now().date().isoformat()
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            dados = response.json()
            return dados if isinstance(dados, list) else dados.get('items', [])
        return []
    except:
        return []

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Dashboard BPO Financeiro", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    # AQUI ESTÁ A MUDANÇA: LER OS TOKENS DA PLANILHA
    try:
        df_tokens = conn.read()
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}")
        st.stop()

    todos_dados = []
    progresso = st.progress(0)
    
    # O loop agora percorre as linhas da planilha
    for i, row in df_tokens.iterrows():
        nome_empresa = row['empresa']
        token_atual = row['refresh_token']
        
        with st.spinner(f'Sincronizando {nome_empresa}...'):
            # Passo 1: Pegar Token de Acesso (e atualizar a planilha)
            acc_token = obter_access_token(nome_empresa, token_atual, df_tokens)
            
            if acc_token:
                # Passo 2: Pegar Lançamentos
                dados_empresa = listar_lancamentos(acc_token)
                if dados_empresa:
                    for item in dados_empresa:
                        item['origem_empresa'] = nome_empresa
                        item['value'] = float(item.get('value', 0))
                    todos_dados.extend(dados_empresa)
        
        # Atualiza barra de progresso baseada no tamanho do DataFrame da planilha
        progresso.progress((i + 1) / len(df_tokens))

    # --- EXIBIÇÃO DOS RESULTADOS ---
    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ Sucesso! {len(df_final)} lançamentos consolidados.")
        
        # Layout de Colunas para Métricas
        col1, col2 = st.columns(2)
        with col1:
            empresas_selecionadas = st.multiselect(
                "Filtrar por Empresa", 
                df_final['origem_empresa'].unique(), 
                default=df_final['origem_empresa'].unique()
            )
            df_filtrado = df_final[df_final['origem_empresa'].isin(empresas_selecionadas)]
        
        with col2:
            if not df_filtrado.empty and 'value' in df_filtrado.columns:
                total_geral = df_filtrado['value'].sum()
                st.metric("Total Movimentado (Período)", f"R$ {total_geral:,.2f}")

        st.subheader("Extrato Consolidado")
        st.dataframe(df_filtrado, use_container_width=True)
    else:
        st.error("Nenhum dado coletado. Verifique os tokens na planilha.")

else:
    st.info("Clique no botão acima para iniciar a coleta de dados via planilha.")
