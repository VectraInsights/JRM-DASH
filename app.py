import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES ---
st.set_page_config(page_title="BPO Dashboard - Fluxo de Caixa", layout="wide")

CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"

auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
B64_AUTH = base64.b64encode(auth_str.encode()).decode()

# --- 2. GOOGLE SHEETS ---
@st.cache_resource
def init_gspread():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["google_sheets"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

sheet = init_gspread()

def get_tokens_db():
    try:
        df = pd.DataFrame(sheet.get_all_records())
        if not df.empty:
            df = df.sort_values(by='empresa', key=lambda col: col.str.lower())
        return df
    except:
        return pd.DataFrame()

def update_refresh_token(empresa, novo_token):
    df = get_tokens_db()
    empresa_up = empresa.upper().strip()
    try:
        idx_list = df.index[df['empresa'].str.upper() == empresa_up].tolist()
        if idx_list:
            sheet.update_cell(idx_list[0] + 2, 2, novo_token)
        else:
            sheet.append_row([empresa_up, novo_token])
    except:
        pass

# --- 3. API CONTA AZUL ---
def refresh_access_token(empresa, refresh_token_atual):
    url = "https://auth.contaazul.com/oauth2/token"
    headers = {"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token_atual}
    res = requests.post(url, headers=headers, data=data)
    if res.status_code == 200:
        dados = res.json()
        update_refresh_token(empresa, dados.get("refresh_token"))
        return dados.get("access_token")
    return None

def fetch_financeiro(token, tipo, d_inicio, d_fim):
    # Endpoints e Parâmetros corrigidos conforme documentação enviada
    base_url = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"
    endpoint = f"{base_url}/contas-a-receber/buscar" if tipo == "receivables" else f"{base_url}/contas-a-pagar/buscar"
    
    params = {
        "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
        "data_vencimento_ate": d_fim.strftime('%Y-%m-%d'),
        "tamanho_pagina": 1000
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(endpoint, headers=headers, params=params)
    
    if res.status_code == 200:
        return res.json()
    return {"erro": res.status_code, "msg": res.text}

# --- 4. INTERFACE ---
st.title("📈 Fluxo de Caixa BPO")

# Lógica de ADM Corrigida
if 'is_admin' not in st.session_state:
    st.session_state.is_admin = False

with st.sidebar:
    st.header("🔍 Filtros")
    df_db = get_tokens_db()
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    
    # Calendário em Português (DD/MM/YYYY)
    hoje = datetime.now()
    d_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
    
    st.divider()
    
    # Login de ADM robusto
    if not st.session_state.is_admin:
        senha = st.text_input("Chave Administrativa", type="password")
        if senha == "8429coconoiaKc#":
            st.session_state.is_admin = True
            st.success("Acesso liberado!")
            st.rerun()
    
    if st.session_state.is_admin:
        st.subheader("⚙️ Admin")
        url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state=ESTADO"
        st.link_button("🔌 Conectar Nova Empresa", url_auth)
        if st.button("Sair do Modo Admin"):
            st.session_state.is_admin = False
            st.rerun()

# --- 5. PROCESSAMENTO ---
if st.button("🚀 Consultar Lançamentos", type="primary"):
    lista_final = []
    logs = []
    processar = empresas if selecao == "TODAS" else [selecao]

    with st.spinner("Buscando dados..."):
        for emp in processar:
            t_ref = df_db.loc[df_db['empresa'] == emp, 'refresh_token'].values[0]
            t_acc = refresh_access_token(emp, t_ref)
            
            if t_acc:
                for t in ["receivables", "payables"]:
                    res = fetch_financeiro(t_acc, t, d_ini, d_fim)
                    # A API v2 retorna os itens diretamente ou em uma chave 'itens'
                    dados = res if isinstance(res, list) else res.get("itens", [])
                    
                    if "erro" in res:
                        logs.append(f"Erro {emp} ({t}): {res['msg']}")
                        continue

                    for item in dados:
                        valor = float(item.get('valor') or item.get('value') or 0)
                        mult = 1 if t == "receivables" else -1
                        lista_final.append({
                            'Data': item.get('data_vencimento') or item.get('due_date'),
                            'Empresa': emp,
                            'Tipo': 'Receita' if mult == 1 else 'Despesa',
                            'Descrição': item.get('descricao') or item.get('description', 'S/D'),
                            'Valor': valor * mult
                        })
            else:
                logs.append(f"Token inválido para: {emp}")

    if lista_final:
        df = pd.DataFrame(lista_final)
        df['Data'] = pd.to_datetime(df['Data']).dt.strftime('%d/%m/%Y')
        
        c1, c2 = st.columns(2)
        c1.metric("Total Receitas", f"R$ {df[df['Valor'] > 0]['Valor'].sum():,.2f}")
        c2.metric("Total Despesas", f"R$ {abs(df[df['Valor'] < 0]['Valor'].sum()):,.2f}")
        
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum lançamento encontrado.")
        if logs: 
            with st.expander("Ver Logs"): st.write(logs)

# --- 6. CALLBACK OAUTH ---
if "code" in st.query_params and st.session_state.is_admin:
    st.divider()
    nome_n = st.text_input("Nome da Nova Empresa:")
    if st.button("Confirmar Vínculo"):
        resp = requests.post("https://auth.contaazul.com/oauth2/token",
                           headers={"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"},
                           data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
        if resp.status_code == 200:
            update_refresh_token(nome_n, resp.json().get("refresh_token"))
            st.success("Conectado!")
            st.rerun()
