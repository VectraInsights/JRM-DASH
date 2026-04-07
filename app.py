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

def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
            "grant_type": "refresh_token", "refresh_token": str(refresh_token_raw).strip()
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

def buscar_apenas_futuros(token, tipo_evento):
    endpoint = f"{URL_BASE_V2}/v1/financeiro/eventos-financeiros/{tipo_evento}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Define amanhã como data de início para ignorar vencidos e hoje
    amanha = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    em_30_dias = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    params = {
        "pagina": 1,
        "tamanho_pagina": 1000,
        "data_vencimento_de": amanha,
        "data_vencimento_ate": em_30_dias,
        "status": "EM_ABERTO"
    }
    try:
        r = requests.get(endpoint, headers=headers, params=params)
        return r.json().get("itens", []) if r.status_code == 200 else []
    except: return []

# --- INTERFACE ---
st.set_page_config(page_title="Fluxo Futuro", layout="wide")
st.title("🚀 Projeção: Próximos 30 Dias (A Vencer)")

if st.button('📊 Calcular Apenas Futuros'):
    # (Lógica de conexão com Google Sheets omitida para brevidade, permanece a mesma)
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        if token:
            for t in ["contas-a-receber", "contas-a-pagar"]:
                itens = buscar_apenas_futuros(token, t)
                label = "Receber" if "receber" in t else "Pagar"
                for i in itens:
                    # Captura de valor conforme documentação V2
                    v_raw = i.get('valor')
                    valor = v_raw.get('valor', 0) if isinstance(v_raw, dict) else (v_raw or i.get('valor_total_liquido', 0))
                    
                    consolidado.append({
                        'data': i.get('data_vencimento'),
                        'valor': float(valor),
                        'tipo': label
                    })

    if consolidado:
        df = pd.DataFrame(consolidado)
        df['data'] = pd.to_datetime(df['data'])
        
        # 1. TOTAIS
        st.divider()
        c1, c2, c3 = st.columns(3)
        r = df[df['tipo'] == 'Receber']['valor'].sum()
        p = df[df['tipo'] == 'Pagar']['valor'].sum()
        c1.metric("A Receber (Futuro)", f"R$ {r:,.2f}")
        c2.metric("A Pagar (Futuro)", f"R$ {p:,.2f}")
        c3.metric("Saldo Projetado", f"R$ {(r - p):,.2f}")

        # 2. GRÁFICO DE TENDÊNCIA
        st.subheader("📈 Curva de Caixa Acumulada")
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        if 'Receber' not in df_g: df_g['Receber'] = 0
        if 'Pagar' not in df_g: df_g['Pagar'] = 0
        
        df_g = df_g.sort_values('data')
        df_g['Saldo'] = df_g['Receber'] - df_g['Pagar']
        df_g['Acumulado'] = df_g['Saldo'].cumsum()
        
        st.area_chart(df_g.set_index('data')[['Acumulado']])
    else:
        st.warning("Não foram encontrados títulos com vencimento futuro para os próximos 30 dias.")
