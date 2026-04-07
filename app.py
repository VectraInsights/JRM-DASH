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

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
            "grant_type": "refresh_token", 
            "refresh_token": str(refresh_token_raw).strip(),
            "scope": "openid profile aws.cognito.signin.user.admin"
        })
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            if novo_refresh:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            return dados.get("access_token")
    except: pass
    return None

def buscar_financeiro_v1_novo(token, tipo):
    # ENDPOINT EXATO DA DOCUMENTAÇÃO ENVIADA
    url = f"https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-{tipo}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Parâmetros obrigatórios conforme a documentação
    params = {
        "pagina": 1,
        "tamanho_pagina": 1000,
        "data_vencimento_de": "2025-01-01T00:00:00Z",
        "data_vencimento_ate": "2027-12-31T23:59:59Z"
    }
    
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            # O retorno costuma ser {'itens': [...]} ou {'items': [...]}
            data = r.json()
            return data.get("items", data.get("itens", []))
        else:
            st.error(f"Erro {tipo}: {r.status_code} - {r.text}")
            return []
    except:
        return []

# --- UI ---
st.set_page_config(page_title="Dashboard Financeiro CA", layout="wide")
st.title("📈 Projeção de Caixa e Totais")

if st.button('🚀 Atualizar Dashboard'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        
        if token:
            with st.status(f"Lendo {emp}...", expanded=False):
                for path, label in [("receber", "Receita"), ("pagar", "Despesa")]:
                    itens = buscar_financeiro_v1_novo(token, path)
                    
                    for i in itens:
                        # Filtro de status: Pega apenas o que não está liquidado
                        # Na V1 o status pode ser 'EM_ABERTO', 'VENCIDO', 'PARCIAL'
                        status = str(i.get('status', '')).upper()
                        if status not in ["QUITADO", "PAGO", "RECEBIDO", "BAIXADO"]:
                            
                            # Captura de valor (Tratando se vier como objeto ou float)
                            v = i.get('valor', 0)
                            val = v if not isinstance(v, dict) else v.get('valor', 0)
                            
                            # Captura de data de vencimento
                            dt_raw = i.get('data_vencimento')
                            dt_venc = pd.to_datetime(dt_raw).date()
                            
                            consolidado.append({
                                'data': dt_venc,
                                'valor': float(val),
                                'tipo': label,
                                'unidade': emp
                            })

    if consolidado:
        df = pd.DataFrame(consolidado)
        
        # --- CARDS DE TOTAIS ---
        tr = df[df['tipo'] == 'Receita']['valor'].sum()
        tp = df[df['tipo'] == 'Despesa']['valor'].sum()
        
        c1, c2, c3 = st.columns(3)
        c1.metric("TOTAL A RECEBER", f"R$ {tr:,.2f}")
        c2.metric("TOTAL A PAGAR", f"R$ {tp:,.2f}")
        c3.metric("SALDO LÍQUIDO", f"R$ {(tr-tp):,.2f}")

        # --- GRÁFICO ---
        st.subheader("📅 Fluxo de Vencimentos")
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)
        for col in ['Receita', 'Despesa']:
            if col not in df_g.columns: df_g[col] = 0
            
        st.bar_chart(df_g[['Receita', 'Despesa']])
        
        with st.expander("Ver Detalhamento Completo"):
            st.dataframe(df.sort_values('data'), use_container_width=True)
    else:
        st.error("Nenhum lançamento encontrado nas datas especificadas.")
