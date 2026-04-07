import streamlit as st
import requests
import pandas as pd
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(
    page_title="Gestão Financeira - Conta Azul",
    page_icon="💰",
    layout="wide"
)

# --- CONSTANTES E AUTH ---
# Substitua pelo seu token real
ACCESS_TOKEN = "SEU_ACCESS_TOKEN_AQUI"
HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

# --- FUNÇÕES DE BUSCA ---
def buscar_contas(tipo, dt_inicio, dt_fim):
    """
    Busca Contas a Pagar ou Receber.
    tipo: 'contas-a-pagar' ou 'contas-a-receber'
    """
    url = f"https://api.contaazul.com/v1/financeiro/{tipo}"
    params = {
        "data_vencimento_de": dt_inicio,
        "data_vencimento_ate": dt_fim,
        "size": 100
    }
    
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            st.error(f"Erro na API ({response.status_code}): {response.text}")
            return []
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return []

# --- INTERFACE SIDEBAR (FILTROS) ---
st.sidebar.image("https://contaazul.com/wp-content/themes/contaazul-v2/img/logo-contaazul.svg", width=150)
st.sidebar.title("Filtros de Análise")

data_de = st.sidebar.date_input("Vencimento Inicial", value=datetime(2026, 4, 1))
data_ate = st.sidebar.date_input("Vencimento Final", value=datetime(2026, 4, 30))

btn_consultar = st.sidebar.button("📊 CONSULTAR AGORA", use_container_width=True)

# --- CORPO DO APP ---
st.title("🚀 Painel de Fluxo de Caixa")
st.markdown(f"Analisando período de **{data_de.strftime('%d/%m/%Y')}** até **{data_ate.strftime('%d/%m/%Y')}**")

if btn_consultar:
    with st.spinner('Buscando dados no Conta Azul...'):
        # Busca os dados
        dados_receber = buscar_contas("contas-a-receber", data_de, data_ate)
        dados_pagar = buscar_contas("contas-a-pagar", data_de, data_ate)

        # Processamento de Dados (Pandas)
        df_receber = pd.DataFrame(dados_receber)
        df_pagar = pd.DataFrame(dados_pagar)

        # Cálculo de Métricas
        val_receber = df_receber['value'].sum() if not df_receber.empty else 0.0
        val_pagar = df_pagar['value'].sum() if not df_pagar.empty else 0.0
        saldo = val_receber - val_pagar

        # Exibição de Cards
        c1, c2, c3 = st.columns(3)
        c1.metric("Total a Receber", f"R$ {val_receber:,.2f}")
        c2.metric("Total a Pagar", f"R$ {val_pagar:,.2f}", delta_color="inverse")
        c3.metric("Saldo Previsto", f"R$ {saldo:,.2f}")

        st.divider()

        # Abas de Detalhamento
        tab_rec, tab_pag = st.tabs(["📈 Entradas (Receber)", "📉 Saídas (Pagar)"])

        with tab_rec:
            if not df_receber.empty:
                # Ajuste de colunas conforme retorno da API V1
                cols_rec = ['customer_name', 'value', 'due_date', 'status']
                display_rec = df_receber[df_receber.columns.intersection(cols_rec)]
                st.dataframe(display_rec, use_container_width=True)
            else:
                st.info("Nenhuma conta a receber para este período.")

        with tab_pag:
            if not df_pagar.empty:
                cols_pag = ['supplier_name', 'value', 'due_date', 'status']
                display_pag = df_pagar[df_pagar.columns.intersection(cols_pag)]
                st.dataframe(display_pag, use_container_width=True)
            else:
                st.info("Nenhuma conta a pagar para este período.")

else:
    st.info("Configure as datas na lateral e clique em Consultar para carregar os dados.")

# --- RODAPÉ ---
st.caption("Desenvolvido para integração direta via API V1 Conta Azul.")
