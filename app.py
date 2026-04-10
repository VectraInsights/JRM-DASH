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
    base_url = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros"
    endpoint = f"{base_url}/contas-a-receber/buscar" if tipo == "receivables" else f"{base_url}/contas-a-pagar/buscar"
    
    # Parâmetros conforme documentação de busca[cite: 8]
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
st.title("📊 Fluxo de Caixa Consolidado")

with st.sidebar:
    st.header("🔍 Filtros")
    df_db = get_tokens_db()
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS AS EMPRESAS"] + empresas)
    
    hoje = datetime.now()
    d_ini = st.date_input("Início", hoje, format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
    
    st.divider()
    
    # Checkbox discreto para Admin[cite: 5]
    is_admin = False
    if st.checkbox("Acesso Administrativo"):
        senha = st.text_input("Chave", type="password")
        if senha == "8429coconoiaKc#":
            is_admin = True
            st.success("Modo Admin Ativo")
            url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state=ESTADO"
            st.link_button("🔌 Conectar Nova Empresa", url_auth)

# --- 5. PROCESSAMENTO ---
if st.button("🚀 Gerar Gráfico de Fluxo", type="primary"):
    lista_final = []
    processar = empresas if selecao == "TODAS AS EMPRESAS" else [selecao]

    with st.spinner("Sincronizando dados bancários..."):
        for emp in processar:
            try:
                t_ref = df_db.loc[df_db['empresa'] == emp, 'refresh_token'].values[0]
                t_acc = refresh_access_token(emp, t_ref)
                
                if t_acc:
                    for t_tipo in ["receivables", "payables"]:
                        res = fetch_financeiro(t_acc, t_tipo, d_ini, d_fim)
                        itens = res if isinstance(res, list) else res.get("itens", [])
                        
                        for item in itens:
                            # CORREÇÃO DE VALOR: A API v2 usa 'valor' ou 'valor_total'[cite: 8]
                            val_bruto = item.get('valor') or item.get('valor_total') or item.get('value') or 0
                            mult = 1 if t_tipo == "receivables" else -1
                            
                            lista_final.append({
                                'Data': pd.to_datetime(item.get('data_vencimento') or item.get('due_date')),
                                'Empresa': emp,
                                'Valor': float(val_bruto) * mult,
                                'Tipo': 'Receita' if mult == 1 else 'Despesa'
                            })
            except:
                continue

    if lista_final:
        df = pd.DataFrame(lista_final)
        
        # --- Dashboards de Topo ---
        c1, c2, c3 = st.columns(3)
        rec = df[df['Valor'] > 0]['Valor'].sum()
        des = abs(df[df['Valor'] < 0]['Valor'].sum())
        c1.metric("Previsto Entradas", f"R$ {rec:,.2f}")
        c2.metric("Previsto Saídas", f"R$ {des:,.2f}", delta_color="inverse")
        c3.metric("Saldo do Período", f"R$ {(rec - des):,.2f}")

        # --- GRÁFICO DE FLUXO DE CAIXA ---
        st.subheader("📈 Projeção Diária de Caixa")
        # Agrupa por dia para o gráfico
        df_diario = df.groupby('Data')['Valor'].sum().reset_index()
        df_diario = df_diario.set_index('Data')
        
        # Gráfico de barras (Saldo Diário)
        st.bar_chart(df_diario)

        # Gráfico Comparativo (Entradas vs Saídas)
        st.subheader("📑 Comparativo Entradas vs Saídas")
        df_comp = df.groupby(['Data', 'Tipo'])['Valor'].sum().abs().unstack().fillna(0)
        st.area_chart(df_comp)

        with st.expander("Ver Detalhes dos Lançamentos"):
            st.dataframe(df, use_container_width=True)
    else:
        st.warning("Nenhum valor encontrado para o período.")

# --- 6. CALLBACK OAUTH ---
if "code" in st.query_params and is_admin:
    st.divider()
    nome_n = st.text_input("Nome da Empresa a cadastrar:")
    if st.button("Confirmar Cadastro"):
        resp = requests.post("https://auth.contaazul.com/oauth2/token",
                           headers={"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"},
                           data={"grant_type": "authorization_code", "code": st.query_params["code"], "redirect_uri": REDIRECT_URI})
        if resp.status_code == 200:
            update_refresh_token(nome_n, resp.json().get("refresh_token"))
            st.success(f"{nome_n} integrada!")
            st.rerun()
