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
    """Busca lançamentos com tratamento de datas e paginação"""
    url = f"https://api-v2.contaazul.com/v1/{tipo}"
    # Formatação rigorosa para a API
    params = {
        "due_after": f"{d_inicio}T00:00:00Z",
        "due_before": f"{d_fim}T23:59:59Z",
        "size": 1000  # Aumentado para evitar vir vazio por paginação
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        return data if isinstance(data, list) else data.get("itens", [])
    return []

# --- 4. INTERFACE ---
st.title("📈 Fluxo de Caixa Inteligente")

with st.sidebar:
    st.header("🔍 Filtros")
    df_db = get_tokens_db()
    empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    
    selecao = st.selectbox("Selecione a Empresa", ["TODAS (CONSOLIDADO)"] + empresas_list)
    
    # Data no padrão brasileiro visualmente
    data_ini = st.date_input("Data Início", datetime.now() - timedelta(days=30), format="DD/MM/YYYY")
    data_fim = st.date_input("Data Fim", datetime.now() + timedelta(days=30), format="DD/MM/YYYY")
    
    st.divider()
    # MODO ADMIN BEM ESCONDIDO (Apenas um checkbox vazio no rodapé da sidebar)
    admin_check = st.checkbox(" ", value=False, help="Área restrita")
    if admin_check:
        senha = st.text_input("Chave de Acesso", type="password")
        if senha == "8429coconoiaKc#":
            st.success("Admin Ativo")
            url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state=ESTADO&scope=openid+profile+aws.cognito.signin.user.admin"
            st.link_button("🔗 Conectar Nova Empresa", url_auth)

# --- 5. LÓGICA DE PROCESSAMENTO ---
if st.button("🚀 Gerar Fluxo de Caixa", type="primary"):
    empresas_para_processar = empresas_list if selecao == "TODAS (CONSOLIDADO)" else [selecao]
    
    all_data = []
    
    with st.spinner(f"Sincronizando dados..."):
        for emp in empresas_para_processar:
            try:
                token_ref = df_db.loc[df_db['empresa'] == emp, 'refresh_token'].values[0]
                token_acc = refresh_access_token(emp, token_ref)
                
                if token_acc:
                    # Busca Receber e Pagar
                    rec = fetch_financeiro(token_acc, "receivables", data_ini, data_fim)
                    pag = fetch_financeiro(token_acc, "payables", data_ini, data_fim)
                    
                    for item in rec:
                        val = item.get('value') or item.get('amount') or 0
                        all_data.append({'data': item['due_date'][:10], 'valor': float(val), 'tipo': 'Entrada', 'desc': item.get('description', 'S/D'), 'empresa': emp})
                    
                    for item in pag:
                        val = item.get('value') or item.get('amount') or 0
                        all_data.append({'data': item['due_date'][:10], 'valor': float(val) * -1, 'tipo': 'Saída', 'desc': item.get('description', 'S/D'), 'empresa': emp})
            except Exception as e:
                st.error(f"Erro na empresa {emp}: {e}")

    if all_data:
        df_total = pd.DataFrame(all_data)
        df_total['data'] = pd.to_datetime(df_total['data'])
        
        # Agrupamento para o gráfico
        grafico_df = df_total.groupby(df_total['data'].dt.date)['valor'].agg([
            ('Entradas', lambda x: x[x > 0].sum()),
            ('Saídas', lambda x: abs(x[x < 0].sum()))
        ]).fillna(0)

        # Métricas
        c1, c2, c3 = st.columns(3)
        total_in = grafico_df['Entradas'].sum()
        total_out = grafico_df['Saídas'].sum()
        c1.metric("Total Entradas", f"R$ {total_in:,.2f}")
        c2.metric("Total Saídas", f"R$ {total_out:,.2f}", delta_color="inverse")
        c3.metric("Saldo Líquido", f"R$ {(total_in - total_out):,.2f}")

        st.subheader(f"Evolução Financeira: {selecao}")
        st.area_chart(grafico_df)

        with st.expander("📄 Detalhamento dos Lançamentos (Lista Completa)"):
            df_view = df_total.sort_values(by='data', ascending=True).copy()
            df_view['data'] = df_view['data'].dt.strftime('%d/%m/%Y')
            st.dataframe(df_view[['data', 'empresa', 'tipo', 'desc', 'valor']], use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum lançamento encontrado. Verifique se o período selecionado possui contas (mesmo que já pagas) na Conta Azul.")

# --- 6. TRATAMENTO DE RETORNO OAUTH (MODO ADMIN) ---
if "code" in st.query_params:
    st.divider()
    st.subheader("🔑 Finalizar Nova Integração")
    code = st.query_params["code"]
    
    nome_emp = st.text_input("Identificação da Empresa para a Planilha:")
    if st.button("Confirmar e Salvar"):
        if nome_emp:
            res = requests.post("https://auth.contaazul.com/oauth2/token", 
                               headers={"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"},
                               data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})
            if res.status_code == 200:
                update_refresh_token(nome_emp, res.json().get("refresh_token"))
                st.success("Salvo!")
                st.query_params.clear()
                st.rerun()
