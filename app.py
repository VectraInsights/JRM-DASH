import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES DE ACESSO ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

# --- 1. CONEXÃO COM GOOGLE SHEETS ---
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
        info["private_key"] = base64.b64decode(b64_key).decode("utf-8").replace("\\n", "\n")
        
        creds = Credentials.from_service_account_info(info, scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ])
        client = gspread.authorize(creds)
        return client.open_by_key(ID_PLANILHA).worksheet("Página1")
    except Exception as e:
        st.error(f"Erro Crítico de Conexão Sheets: {e}")
        st.stop()

# --- 2. RENOVAÇÃO DE TOKEN ---
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
    except:
        pass
    return None

# --- 3. BUSCA NA API V2 (SEM FILTROS DE DATA NA URL) ---
def buscar_api_v2(token, path):
    """Busca os itens sem filtros de data para evitar que a API retorne vazio por erro de sintaxe"""
    url = f"https://api-v2.contaazul.com/v1/financeiro/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    # Trazemos uma massa de dados maior para filtrar no Python
    params = {"pagina": 1, "tamanho_pagina": 100}
    
    try:
        # Tenta a rota direta
        r = requests.get(url, headers=headers, params=params)
        if r.status_code != 200:
            # Tenta com o sufixo /buscar se a primeira falhar
            r = requests.get(f"{url}/buscar", headers=headers, params=params)
        
        if r.status_code == 200:
            return r.json().get("itens", [])
    except:
        pass
    return []

# --- 4. INTERFACE PRINCIPAL ---
st.set_page_config(page_title="Dashboard Financeiro JRM", layout="wide")

st.title("🚀 Fluxo de Caixa Futuro (Próximos 30 Dias)")
st.info("Este painel exibe apenas títulos que **vencem de amanhã em diante**.")

if st.button('📊 Processar Unidades'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    
    lista_final = []
    
    # Definindo balizadores de data (Hoje é 07/04/2026)
    hoje = datetime.now()
    amanha = (hoje + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    limite_futuro = amanha + timedelta(days=30)

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        
        if token:
            with st.expander(f"Processando {emp}", expanded=False):
                # Busca Receber e Pagar
                for rota in [("contas-a-receber", "Receita"), ("contas-a-pagar", "Despesa")]:
                    itens = buscar_api_v2(token, rota[0])
                    count_unidade = 0
                    
                    for i in itens:
                        # Filtro 1: Status (Somente o que não foi pago/recebido totalmente)
                        status = i.get('status', '').upper()
                        if status in ['EM_ABERTO', 'RECEBIDO_PARCIAL', 'PAGO_PARCIAL']:
                            
                            # Filtro 2: Data de Vencimento
                            dt_venc = pd.to_datetime(i.get('data_vencimento'))
                            
                            if dt_venc >= amanha and dt_venc <= limite_futuro:
                                # Filtro 3: Captura de Valor (Tratando objeto ou número)
                                v = i.get('valor')
                                valor_num = v.get('valor', 0) if isinstance(v, dict) else (v or 0)
                                
                                if valor_num > 0:
                                    lista_final.append({
                                        'Unidade': emp,
                                        'Data': dt_venc,
                                        'Valor': float(valor_num),
                                        'Tipo': rota[1]
                                    })
                                    count_unidade += 1
                    
                    st.write(f"✅ {rota[1]}: {count_unidade} títulos encontrados.")

    # --- EXIBIÇÃO DOS RESULTADOS ---
    if lista_final:
        df = pd.DataFrame(lista_final)
        
        # Métricas de Topo
        st.divider()
        c1, c2, c3 = st.columns(3)
        
        total_rec = df[df['Tipo'] == 'Receita']['Valor'].sum()
        total_desp = df[df['Tipo'] == 'Despesa']['Valor'].sum()
        saldo = total_rec - total_desp

        c1.metric("Receber (A Vencer)", f"R$ {total_rec:,.2f}")
        c2.metric("Pagar (A Vencer)", f"R$ {total_desp:,.2f}")
        c3.metric("Saldo do Período", f"R$ {saldo:,.2f}", delta=f"{saldo:,.2f}")

        # Gráfico de Evolução
        st.subheader("📈 Evolução do Saldo Acumulado")
        df_plot = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        
        # Garantir colunas para não quebrar o gráfico
        if 'Receita' not in df_plot: df_plot['Receita'] = 0
        if 'Despesa' not in df_plot: df_plot['Despesa'] = 0
        
        df_plot = df_plot.sort_values('Data')
        df_plot['Saldo_Dia'] = df_plot['Receita'] - df_plot['Despesa']
        df_plot['Acumulado'] = df_plot['Saldo_Dia'].cumsum()
        
        st.area_chart(df_plot.set_index('Data')[['Acumulado']])
        
        # Tabela Detalhada
        with st.expander("Ver lista detalhada de títulos"):
            st.dataframe(df.sort_values('Data'), use_container_width=True)
            
    else:
        st.error("❌ Nenhum dado encontrado para os critérios selecionados.")
        st.warning("Verifique se as contas no Conta Azul estão com status 'Em Aberto' e se o vencimento é após hoje.")
