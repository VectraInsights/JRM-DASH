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
    return pd.DataFrame(sheet.get_all_records())

def update_refresh_token(empresa, novo_token):
    df = get_tokens_db()
    try:
        idx = df.index[df['empresa'].str.upper() == empresa.upper()].tolist()[0] + 2
        sheet.update_cell(idx, 2, novo_token)
    except:
        sheet.append_row([empresa.upper(), novo_token])

# --- 3. API CONTA AZUL (FINANCEIRO) ---
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
    """tipo: 'receivables' ou 'payables'"""
    # Formato da data: YYYY-MM-DDTHH:mm:ssZ
    url = f"https://api-v2.contaazul.com/v1/{tipo}"
    params = {
        "due_after": f"{d_inicio}T00:00:00Z",
        "due_before": f"{d_fim}T23:59:59Z",
        "status": "OPEN" # Buscando apenas o que está aberto para o fluxo futuro
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers, params=params).json()
    return res if isinstance(res, list) else res.get("itens", [])

# --- 4. UI ---
st.title("📈 Fluxo de Caixa Consolidado")

# Filtros na Sidebar
st.sidebar.header("Parâmetros")
df_db = get_tokens_db()
empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
empresa_selecionada = st.sidebar.selectbox("Selecione a Empresa", empresas)

# Seleção de Período
hoje = datetime.now()
data_ini = st.sidebar.date_input("Data Início", hoje - timedelta(days=30))
data_fim = st.sidebar.date_input("Data Fim", hoje + timedelta(days=30))

if empresa_selecionada:
    token_ref = df_db.loc[df_db['empresa'] == empresa_selecionada, 'refresh_token'].values[0]
    
    if st.button("📊 Gerar Fluxo de Caixa", type="primary"):
        with st.spinner("Processando lançamentos..."):
            token_acc = refresh_access_token(empresa_selecionada, token_ref)
            
            if token_acc:
                # Busca os dois lados da moeda
                receber = fetch_financeiro(token_acc, "receivables", data_ini, data_fim)
                pagar = fetch_financeiro(token_acc, "payables", data_ini, data_fim)
                
                # Processamento
                df_rec = pd.DataFrame(receber)
                df_pag = pd.DataFrame(pagar)
                
                # Normalização de dados
                for df, label, mult in [(df_rec, 'Receber', 1), (df_pag, 'Pagar', -1)]:
                    if not df.empty:
                        df['valor'] = df['value'].astype(float) * mult
                        df['data'] = pd.to_datetime(df['due_date']).dt.date
                    else:
                        # Cria DF vazio compatível se não houver dados
                        df['data'] = []
                        df['valor'] = []

                # Merge e Gráfico
                resumo_rec = df_rec.groupby('data')['valor'].sum().reset_index() if not df_rec.empty else pd.DataFrame(columns=['data', 'valor'])
                resumo_pag = df_pag.groupby('data')['valor'].sum().reset_index() if not df_pag.empty else pd.DataFrame(columns=['data', 'valor'])
                
                # Criação do DataFrame de Fluxo
                fluxo = pd.merge(resumo_rec, resumo_pag, on='data', how='outer', suffixes=('_in', '_out')).fillna(0)
                fluxo['Saldo Diário'] = fluxo['valor_in'] + fluxo['valor_out']
                fluxo = fluxo.sort_values('data')
                
                # Exibição de Métricas
                c1, c2, c3 = st.columns(3)
                c1.metric("Total a Receber", f"R$ {fluxo['valor_in'].sum():,.2f}")
                c2.metric("Total a Pagar", f"R$ {abs(fluxo['valor_out'].sum()):,.2f}", delta_color="inverse")
                c3.metric("Saldo do Período", f"R$ {fluxo['Saldo Diário'].sum():,.2f}")

                # Gráfico
                st.subheader("Evolução do Fluxo de Caixa")
                chart_data = fluxo.set_index('data')[['valor_in', 'valor_out']]
                chart_data.columns = ['Entradas', 'Saídas']
                st.area_chart(chart_data)

                # Tabela de Detalhes
                with st.expander("Ver lista detalhada de lançamentos"):
                    st.write("### Contas a Receber")
                    st.table(df_rec[['due_date', 'description', 'value']] if not df_rec.empty else [])
                    st.write("### Contas a Pagar")
                    st.table(df_pag[['due_date', 'description', 'value']] if not df_pag.empty else [])
