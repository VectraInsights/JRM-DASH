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
            "grant_type": "refresh_token", "refresh_token": str(refresh_token_raw).strip()
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

def buscar_parcelas_v2(token, tipo):
    """
    Usa o endpoint de parcelas, que é o mais completo da V2.
    tipo: 'receber' ou 'pagar'
    """
    url = f"https://api-v2.contaazul.com/v1/financeiro/contas-a-{tipo}/parcelas"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    # Sem filtros de data aqui para garantir que a API não barre nada
    params = {"pagina": 1, "tamanho_pagina": 500}
    
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            return r.json().get("itens", [])
        return []
    except:
        return []

# --- UI ---
st.set_page_config(page_title="Fluxo de Caixa 30D", layout="wide")
st.title("📈 Projeção de Caixa (Próximos 30 Dias)")

if st.button('🚀 Executar Varredura Completa'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    # Período: Amanhã até +30 dias
    hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    amanha = hoje + timedelta(days=1)
    limite = hoje + timedelta(days=31)

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'], aba)
        
        if token:
            with st.status(f"Lendo {emp}...", expanded=True):
                # Processa Recebíveis
                recs = buscar_parcelas_v2(token, "receber")
                count_r = 0
                for i in recs:
                    # Na V2 o status de parcelas é numérico ou string. Verificamos 'EM_ABERTO'
                    status = str(i.get('status', '')).upper()
                    if "ABERTO" in status or "PARCIAL" in status:
                        dt_venc = pd.to_datetime(i.get('data_vencimento'))
                        
                        if dt_venc >= amanha and dt_venc <= limite:
                            v = i.get('valor', 0)
                            # Trata se o valor vier como objeto
                            val = v.get('valor', 0) if isinstance(v, dict) else v
                            consolidado.append({'data': dt_venc, 'valor': float(val), 'tipo': 'Receita', 'unidade': emp})
                            count_r += 1
                
                # Processa Pagamentos
                pags = buscar_parcelas_v2(token, "pagar")
                count_p = 0
                for i in pags:
                    status = str(i.get('status', '')).upper()
                    if "ABERTO" in status or "PARCIAL" in status:
                        dt_venc = pd.to_datetime(i.get('data_vencimento'))
                        
                        if dt_venc >= amanha and dt_venc <= limite:
                            v = i.get('valor', 0)
                            val = v.get('valor', 0) if isinstance(v, dict) else v
                            consolidado.append({'data': dt_venc, 'valor': float(val), 'tipo': 'Despesa', 'unidade': emp})
                            count_p += 1
                
                st.write(f"✅ Finalizado: {count_r} receitas e {count_p} despesas futuras.")

    if consolidado:
        df = pd.DataFrame(consolidado)
        st.divider()
        
        c1, c2, c3 = st.columns(3)
        tr = df[df['tipo'] == 'Receita']['valor'].sum()
        tp = df[df['tipo'] == 'Despesa']['valor'].sum()
        
        c1.metric("Receber (Futuro)", f"R$ {tr:,.2f}")
        c2.metric("Pagar (Futuro)", f"R$ {tp:,.2f}")
        c3.metric("Saldo Líquido", f"R$ {(tr-tp):,.2f}")

        # Gráfico
        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0).reset_index()
        if 'Receita' not in df_g: df_g['Receita'] = 0
        if 'Despesa' not in df_g: df_g['Despesa'] = 0
        df_g = df_g.sort_values('data')
        df_g['Acumulado'] = (df_g['Receita'] - df_g['Despesa']).cumsum()
        st.area_chart(df_g.set_index('data')['Acumulado'])
        
        st.write("### Detalhamento")
        st.dataframe(df)
    else:
        st.error("ERRO: A API retornou listas vazias para todas as unidades.")
        st.info("Verifique se os lançamentos no Conta Azul não estão marcados apenas como 'Vendas' sem ter gerado o financeiro (parcelas).")
