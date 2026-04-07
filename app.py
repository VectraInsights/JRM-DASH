import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- 1. CONFIGURAÇÕES DE ACESSO ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    """Conecta ao Google Sheets usando as credenciais do Streamlit Secrets."""
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
    # Decodifica a chave privada que está em Base64 para evitar erros de formatação
    b64_key = gs["private_key_base64"]
    info["private_key"] = base64.b64decode(b64_key).decode("utf-8").replace("\\n", "\n")
    
    creds = Credentials.from_service_account_info(
        info, 
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    return gspread.authorize(creds).open_by_key(ID_PLANILHA).worksheet("Página1")

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    """Renova o Access Token usando o Refresh Token da planilha."""
    url = "https://auth.contaazul.com/oauth2/token"
    refresh_token_clean = str(refresh_token_raw).strip()
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_clean,
        "scope": "openid profile aws.cognito.signin.user.admin"
    }
    
    try:
        response = requests.post(
            url, 
            auth=(CLIENT_ID, CLIENT_SECRET), 
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Se a API rotacionar o Refresh Token, atualizamos a planilha
            if novo_refresh and novo_refresh != refresh_token_clean:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
        else:
            st.error(f"❌ Erro Auth ({empresa}): {response.status_code} - {response.text}")
            return None
    except Exception as e:
        st.error(f"💥 Falha de conexão na Auth: {e}")
        return None

def buscar_dados_financeiros(token, tipo):
    """Busca lançamentos usando o endpoint oficial v1/buscar."""
    url = f"https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-{tipo}/buscar"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    # Filtro de data amplo para garantir que tragamos os lançamentos futuros
    params = {
        "pagina": 1,
        "tamanho_pagina": 1000,
        "data_vencimento_de": "2025-01-01T00:00:00Z",
        "data_vencimento_ate": "2027-12-31T23:59:59Z"
    }
    
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            data = r.json()
            # Retorna a lista de itens (aceita 'items' ou 'itens')
            return data.get("items", data.get("itens", []))
        else:
            st.warning(f"⚠️ Erro API {tipo.upper()}: {r.status_code} - Verifique permissões.")
            return []
    except Exception as e:
        st.error(f"💥 Erro na busca de {tipo}: {e}")
        return []

# --- 2. INTERFACE E LÓGICA DO DASHBOARD ---
st.set_page_config(page_title="Gestão Financeira Consolidada", layout="wide")

st.markdown("### 📊 Consolidador Financeiro Conta Azul")
st.caption("Filtro: Janeiro/2025 a Dezembro/2027 | Somente lançamentos em aberto.")

if st.button('🚀 Atualizar e Processar Dados'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        
        if token:
            with st.status(f"Processando {emp}...", expanded=False) as status:
                for path, label in [("receber", "Receita"), ("pagar", "Despesa")]:
                    itens = buscar_dados_financeiros(token, path)
                    
                    for i in itens:
                        # Filtragem de status para garantir que o dashboard mostre apenas o pendente
                        st_item = str(i.get('status', '')).upper()
                        if st_item not in ["QUITADO", "PAGO", "RECEBIDO", "BAIXADO"]:
                            
                            # Tratamento de valor (pode vir como número ou objeto {'valor': 0.0})
                            v = i.get('valor', 0)
                            valor_final = v if not isinstance(v, dict) else v.get('valor', 0)
                            
                            # Formatação de data
                            dt_raw = i.get('data_vencimento')
                            dt_venc = pd.to_datetime(dt_raw).date()
                            
                            consolidado.append({
                                'unidade': emp,
                                'tipo': label,
                                'data': dt_venc,
                                'valor': float(valor_final),
                                'status': st_item
                            })
                status.update(label=f"✅ {emp} concluído!", state="complete")

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # --- SEÇÃO DE INDICADORES ---
        total_receber = df[df['tipo'] == 'Receita']['valor'].sum()
        total_pagar = df[df['tipo'] == 'Despesa']['valor'].sum()
        saldo = total_receber - total_pagar
        
        col1, col2, col3 = st.columns(3)
        col1.metric("TOTAL A RECEBER", f"R$ {total_receber:,.2f}")
        col2.metric("TOTAL A PAGAR", f"R$ {total_pagar:,.2f}", delta_color="inverse")
        col3.metric("SALDO PROJETADO", f"R$ {saldo:,.2f}", delta=f"{saldo:,.2f}")

        # --- SEÇÃO DE GRÁFICO ---
        st.write("---")
        st.subheader("📅 Projeção de Fluxo de Caixa (Vencimentos)")
        
        # Agrupa por data e tipo para o gráfico de barras
        df_grafico = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)
        
        # Garante que ambas as colunas existam para não quebrar o gráfico
        for col in ['Receita', 'Despesa']:
            if col not in df_grafico.columns:
                df_grafico[col] = 0
        
        st.bar_chart(df_grafico[['Receita', 'Despesa']])

        # --- SEÇÃO DE TABELA ---
        with st.expander("🔍 Ver detalhes de todos os lançamentos"):
            st.dataframe(df.sort_values(by='data'), use_container_width=True)
            
    else:
        st.error("Nenhum dado foi encontrado. Verifique os Refresh Tokens ou se há lançamentos no Conta Azul.")
