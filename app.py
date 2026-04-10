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
    df = pd.DataFrame(sheet.get_all_records())
    if not df.empty:
        # Organiza as empresas em ordem alfabética
        df = df.sort_values(by='empresa')
    return df

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
    url = f"https://api-v2.contaazul.com/v1/{tipo}"
    # Formatação exata ISO8601 exigida pela Conta Azul
    params = {
        "due_after": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
        "due_before": d_fim.strftime('%Y-%m-%dT23:59:59Z'),
        "size": 1000
    }
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(url, headers=headers, params=params)
    
    if res.status_code == 200:
        data = res.json()
        return data if isinstance(data, list) else data.get("itens", [])
    return {"status": res.status_code, "body": res.text}

# --- 4. INTERFACE ---
st.title("📈 Fluxo de Caixa Inteligente")

# Validação Admin robusta
user_email = st.user.email if st.user else "visitante"
is_admin = (user_email == "sptn201169@gmail.com")

with st.sidebar:
    st.header("🔍 Filtros")
    df_db = get_tokens_db()
    empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    
    selecao = st.selectbox("Selecione a Empresa", ["TODAS (CONSOLIDADO)"] + empresas_list)
    
    # Calendário com datas automáticas conforme solicitado
    data_ini = st.date_input("Data Início", datetime.now(), format="DD/MM/YYYY")
    data_fim = st.date_input("Data Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.divider()
    
    if is_admin:
        st.success(f"Logado como: {user_email}")
        url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state=ESTADO&scope=openid+profile+aws.cognito.signin.user.admin"
        st.link_button("🔗 Conectar Nova Empresa", url_auth)
    else:
        st.error("Acesso restrito para novos vínculos.")
        # Botão secreto temporário caso o st.user falhe no seu navegador
        if st.checkbox("Usar Chave Manual (Admin Only)"):
            chave = st.text_input("Insira a chave", type="password")
            if chave == "8429coconoiaKc#":
                is_admin = True
                st.rerun()

# --- 5. LÓGICA DE PROCESSAMENTO ---
if st.button("🚀 Gerar Fluxo de Caixa", type="primary"):
    empresas_para_processar = empresas_list if selecao == "TODAS (CONSOLIDADO)" else [selecao]
    all_data = []
    logs_erro = []

    with st.spinner("Sincronizando com Conta Azul..."):
        for emp in empresas_para_processar:
            token_ref = df_db.loc[df_db['empresa'] == emp, 'refresh_token'].values[0]
            token_acc = refresh_access_token(emp, token_ref)
            
            if token_acc:
                for tipo in ["receivables", "payables"]:
                    resultado = fetch_financeiro(token_acc, tipo, data_ini, data_fim)
                    
                    if isinstance(resultado, list):
                        for item in resultado:
                            # Tenta pegar valor de múltiplos campos possíveis na API
                            val = item.get('value') or item.get('amount') or 0
                            mult = 1 if tipo == "receivables" else -1
                            all_data.append({
                                'Data': item['due_date'][:10],
                                'Empresa': emp,
                                'Tipo': 'Entrada' if mult == 1 else 'Saída',
                                'Descrição': item.get('description', 'S/D'),
                                'Valor': float(val) * mult
                            })
                    else:
                        logs_erro.append(f"Erro em {emp} ({tipo}): {resultado}")
            else:
                logs_erro.append(f"Falha ao renovar token da empresa: {emp}")

    if all_data:
        df_total = pd.DataFrame(all_data)
        df_total['Data'] = pd.to_datetime(df_total['Data'])
        
        # Dashboard Visual
        c1, c2, c3 = st.columns(3)
        total_in = df_total[df_total['Valor'] > 0]['Valor'].sum()
        total_out = abs(df_total[df_total['Valor'] < 0]['Valor'].sum())
        
        c1.metric("Total Entradas", f"R$ {total_in:,.2f}")
        c2.metric("Total Saídas", f"R$ {total_out:,.2f}", delta_color="inverse")
        c3.metric("Saldo do Período", f"R$ {(total_in - total_out):,.2f}")

        # Gráfico Consolidado
        grafico = df_total.groupby(df_total['Data'].dt.date)['Valor'].sum()
        st.subheader("Tendência de Caixa (Saldo Diário)")
        st.line_chart(grafico)

        with st.expander("📄 Ver Lista de Lançamentos Detalhada"):
            df_display = df_total.sort_values(by='Data')
            df_display['Data'] = df_display['Data'].dt.strftime('%d/%m/%Y')
            st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum lançamento encontrado. Tente aumentar o intervalo de datas.")
        if logs_erro:
            with st.expander("⚠️ Detalhes Técnicos (Erros de API)"):
                for erro in logs_erro:
                    st.write(erro)

# --- 6. RETORNO OAUTH ---
if "code" in st.query_params and is_admin:
    st.divider()
    st.info("Nova autorização detectada!")
    code = st.query_params["code"]
    nome_nova = st.text_input("Nome da Nova Empresa:")
    if st.button("Finalizar Cadastro"):
        # Logica de troca de code por token... (mantida do anterior)
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
                           headers={"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"},
                           data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI})
        if res.status_code == 200:
            update_refresh_token(nome_nova, res.json().get("refresh_token"))
            st.success("Vinculado com sucesso!")
            st.rerun()
