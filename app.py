import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- 1. CONFIGURAÇÕES ---
st.set_page_config(page_title="BPO Dashboard - Fluxo de Caixa", layout="wide")

# Credenciais
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
    return pd.DataFrame(sheet.get_all_records())

def update_refresh_token(empresa, novo_token):
    df = get_tokens_db()
    empresa_up = empresa.upper().strip()
    try:
        idx = df.index[df['empresa'].str.upper() == empresa_up].tolist()[0] + 2
        sheet.update_cell(idx, 2, novo_token)
    except:
        sheet.append_row([empresa_up, novo_token])

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
    """Busca lançamentos. Removido filtro de status para trazer tudo do período."""
    url = f"https://api-v2.contaazul.com/v1/{tipo}"
    params = {
        "due_after": f"{d_inicio}T00:00:00Z",
        "due_before": f"{d_fim}T23:59:59Z"
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers, params=params).json()
    return res if isinstance(res, list) else res.get("itens", [])

# --- 4. INTERFACE ---
st.title("📈 Fluxo de Caixa Inteligente")

# --- MODO ADMIN (Proteção de Conexão) ---
with st.sidebar:
    st.header("⚙️ Configurações")
    admin_mode = st.toggle("Modo Administrador")
    if admin_mode:
        senha = st.text_input("Senha de acesso", type="password")
        if senha == "admin123": # Altere sua senha aqui
            st.success("Acesso liberado")
            url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state=ESTADO&scope=openid+profile+aws.cognito.signin.user.admin"
            st.link_button("🔗 Conectar Nova Empresa", url_auth)
        elif senha:
            st.error("Senha incorreta")

    st.divider()
    st.header("🔍 Filtros")
    df_db = get_tokens_db()
    empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    
    selecao = st.selectbox("Empresa", ["TODAS (CONSOLIDADO)"] + empresas_list)
    
    data_ini = st.date_input("Data Início", datetime.now() - timedelta(days=30), format="DD/MM/YYYY")
    data_fim = st.date_input("Data Fim", datetime.now() + timedelta(days=30), format="DD/MM/YYYY")

# --- LÓGICA DE PROCESSAMENTO ---
if st.button("🚀 Gerar Fluxo de Caixa", type="primary"):
    empresas_para_processar = empresas_list if selecao == "TODAS (CONSOLIDADO)" else [selecao]
    
    all_data_in = []
    all_data_out = []
    
    with st.spinner(f"Processando {len(empresas_para_processar)} empresa(s)..."):
        for emp in empresas_para_processar:
            token_ref = df_db.loc[df_db['empresa'] == emp, 'refresh_token'].values[0]
            token_acc = refresh_access_token(emp, token_ref)
            
            if token_acc:
                rec = fetch_financeiro(token_acc, "receivables", data_ini, data_fim)
                pag = fetch_financeiro(token_acc, "payables", data_ini, data_fim)
                
                for item in rec:
                    all_data_in.append({'data': item['due_date'][:10], 'valor': float(item['value']), 'empresa': emp})
                for item in pag:
                    all_data_out.append({'data': item['due_date'][:10], 'valor': float(item['value']) * -1, 'empresa': emp})

    if all_data_in or all_data_out:
        df_in = pd.DataFrame(all_data_in)
        df_out = pd.DataFrame(all_data_out)
        
        # Consolidação para o Gráfico
        df_total = pd.concat([df_in, df_out])
        df_total['data'] = pd.to_datetime(df_total['data'])
        
        grafico_df = df_total.groupby(df_total['data'].dt.date)['valor'].agg([
            ('Entradas', lambda x: x[x > 0].sum()),
            ('Saídas', lambda x: abs(x[x < 0].sum()))
        ]).fillna(0)

        # Métricas
        c1, c2, c3 = st.columns(3)
        total_rec = grafico_df['Entradas'].sum()
        total_pag = grafico_df['Saídas'].sum()
        c1.metric("Total a Receber", f"R$ {total_rec:,.2f}")
        c2.metric("Total a Pagar", f"R$ {total_pag:,.2f}", delta_color="inverse")
        c3.metric("Saldo Líquido", f"R$ {(total_rec - total_pag):,.2f}")

        # Gráfico de Área
        st.subheader(f"Evolução: {selecao}")
        st.area_chart(grafico_df)

        # Tabela Detalhada com data BR
        with st.expander("Ver lançamentos detalhados"):
            df_table = df_total.copy()
            df_table['data'] = df_table['data'].dt.strftime('%d/%m/%Y')
            df_table['valor'] = df_table['valor'].map('R$ {:,.2f}'.format)
            st.dataframe(df_table, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum lançamento encontrado para o período/empresa selecionada.")

# --- TRATAMENTO DE RETORNO OAUTH ---
if "code" in st.query_params:
    st.info("Nova autorização detectada...")
    # ... (mesma lógica de vinculação anterior)
