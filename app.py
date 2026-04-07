import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials

# --- CONFIGURAÇÕES ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = "67rc11hjc0qt863nql0b20vjg0"
CLIENT_SECRET = "2pgl713loumm8rl0atfrh9i9ja6oi18l2pmqunjbr66qfiqosg2"

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

def obter_access_token(empresa, refresh_token_raw):
    url = "https://auth.contaazul.com/oauth2/token"
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data={
            "grant_type": "refresh_token", 
            "refresh_token": str(refresh_token_raw).strip(),
            "scope": "openid profile aws.cognito.signin.user.admin"
        })
        return response.json().get("access_token") if response.status_code == 200 else None
    except: return None

def buscar_dados_v1(token, tipo):
    # Testando o endpoint principal
    url = f"https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-{tipo}/buscar"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    
    # Tentativa 1: Formato de data simples (YYYY-MM-DD) - Mais comum em APIs legadas que migraram
    params = {
        "pagina": 1, 
        "tamanho_pagina": 1000,
        "data_vencimento_de": "2025-01-01",
        "data_vencimento_ate": "2027-12-31"
    }
    
    r = requests.get(url, headers=headers, params=params)
    
    # Se retornar vazio, tentamos sem filtros de data (para ver se vem QUALQUER coisa)
    if r.status_code == 200 and not r.json().get("items", r.json().get("itens", [])):
        st.info(f"Tentando busca global para {tipo}...")
        r = requests.get(url, headers=headers, params={"pagina": 1, "tamanho_pagina": 100})

    if r.status_code == 200:
        res = r.json()
        return res.get("items", res.get("itens", []))
    return []

# --- DASHBOARD ---
st.title("📊 Painel Financeiro - Diagnóstico de Dados")

if st.button('🚀 Iniciar Sincronização'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()
    consolidado = []

    for row in linhas:
        emp = row['empresa']
        token = obter_access_token(emp, row['refresh_token'])
        
        if token:
            with st.status(f"Processando {emp}...") as s:
                for t, label in [("receber", "Receita"), ("pagar", "Despesa")]:
                    itens = buscar_dados_v1(token, t)
                    
                    st.write(f"📡 API {label}: {len(itens)} registros brutos retornados.")
                    
                    for i in itens:
                        # Captura flexível de valores (vários nomes possíveis na API)
                        val = 0
                        for campo in ['valor', 'valor_nominal', 'valor_total']:
                            v = i.get(campo)
                            if v:
                                val = v.get('valor', v) if isinstance(v, dict) else v
                                break
                        
                        # Captura flexível de datas
                        data_bruta = i.get('data_vencimento') or i.get('vencimento')
                        
                        # Filtro de status robusto
                        status = str(i.get('status', '')).upper()
                        if status not in ["QUITADO", "PAGO", "RECEBIDO", "BAIXADO"]:
                            consolidado.append({
                                'data': pd.to_datetime(data_bruta).date(),
                                'valor': float(val),
                                'tipo': label,
                                'unidade': emp
                            })
                s.update(label="Sincronização Finalizada!", state="complete")

    if consolidado:
        df = pd.DataFrame(consolidado)
        c1, c2, c3 = st.columns(3)
        rec = df[df['tipo'] == 'Receita']['valor'].sum()
        des = df[df['tipo'] == 'Despesa']['valor'].sum()
        c1.metric("A RECEBER", f"R$ {rec:,.2f}")
        c2.metric("A PAGAR", f"R$ {des:,.2f}")
        c3.metric("SALDO", f"R$ {(rec-des):,.2f}")
        
        st.bar_chart(df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0))
        st.write("### Lista de Lançamentos Capturados")
        st.dataframe(df)
    else:
        st.error("🚨 A API conectou, mas a lista de itens continua vindo vazia.")
        st.info("Isso pode significar que o seu Token tem acesso à API, mas não tem permissão para enxergar os dados da empresa JTL. Verifique se o usuário que gerou o Token tem permissão de 'Administrador' ou 'Financeiro' dentro do Conta Azul.")
