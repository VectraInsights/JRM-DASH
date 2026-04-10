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
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty:
            # Ordenação alfabética das empresas
            df = df.sort_values(by='empresa', key=lambda col: col.str.lower())
        return df
    except Exception as e:
        st.error(f"Erro ao acessar banco de dados: {e}")
        return pd.DataFrame()

def update_refresh_token(empresa, novo_token):
    df = get_tokens_db()
    empresa_up = empresa.upper().strip()
    try:
        # Tenta localizar a linha para atualizar, se não existir, anexa
        idx_list = df.index[df['empresa'].str.upper() == empresa_up].tolist()
        if idx_list:
            row_idx = idx_list[0] + 2 # +2 por conta do header e índice 0
            sheet.update_cell(row_idx, 2, novo_token)
        else:
            sheet.append_row([empresa_up, novo_token])
    except Exception as e:
        st.error(f"Erro ao atualizar token: {e}")

# --- 3. API CONTA AZUL (OAUTH & FETCH) ---
def refresh_access_token(empresa, refresh_token_atual):
    url = "https://auth.contaazul.com/oauth2/token"
    headers = {
        "Authorization": f"Basic {B64_AUTH}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_atual
    }
    res = requests.post(url, headers=headers, data=data)
    if res.status_code == 200:
        dados = res.json()
        update_refresh_token(empresa, dados.get("refresh_token"))
        return dados.get("access_token")
    return None

def fetch_financeiro(token, tipo, d_inicio, d_fim):
    # Endpoints atualizados para evitar Erro 404
    if tipo == "receivables":
        url = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-receber/buscar"
    else:
        url = "https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar"
    
    params = {
        "due_date_start": d_inicio.strftime('%Y-%m-%d'),
        "due_date_end": d_fim.strftime('%Y-%m-%d'),
        "size": 1000
    }
    headers = {"Authorization": f"Bearer {token}"}
    
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200:
        return res.json()
    return {"erro": res.status_code, "msg": res.text}

# --- 4. INTERFACE ---
st.title("📈 Fluxo de Caixa Consolidado (BPO)")

# Verificação de Admin
user_email = st.user.email if st.user else "deslogado"
admin_email = "sptn201169@gmail.com"
is_admin = (user_email == admin_email)

with st.sidebar:
    st.header("🔍 Filtros de Busca")
    df_db = get_tokens_db()
    empresas_list = df_db['empresa'].unique().tolist() if not df_db.empty else []
    
    selecao = st.selectbox("Selecione a Empresa", ["TODAS (CONSOLIDADO)"] + empresas_list)
    
    # Datas: Hoje a Hoje + 7
    hoje = datetime.now()
    data_ini = st.date_input("Data Início", hoje, format="DD/MM/YYYY")
    data_fim = st.date_input("Data Fim", hoje + timedelta(days=7), format="DD/MM/YYYY")
    
    st.divider()
    
    # Login Manual de Admin (caso o e-mail não seja detectado)
    if not is_admin:
        with st.expander("Acesso Administrativo"):
            senha = st.text_input("Chave de Acesso", type="password")
            if senha == "8429coconoiaKc#":
                is_admin = True
                st.success("Admin Autorizado")
            elif senha != "":
                st.error("Senha incorreta.")

    if is_admin:
        st.subheader("Gerenciamento")
        url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&state=ESTADO&scope=openid+profile+aws.cognito.signin.user.admin"
        st.link_button("🔗 Conectar Nova Empresa", url_auth)

# --- 5. PROCESSAMENTO E EXIBIÇÃO ---
if st.button("🚀 Gerar Fluxo de Caixa", type="primary"):
    empresas_alvo = empresas_list if selecao == "TODAS (CONSOLIDADO)" else [selecao]
    fluxo_data = []
    erros_log = []

    with st.spinner(f"Coletando dados de {len(empresas_alvo)} empresa(s)..."):
        for emp in empresas_alvo:
            try:
                token_ref = df_db.loc[df_db['empresa'] == emp, 'refresh_token'].values[0]
                token_acc = refresh_access_token(emp, token_ref)
                
                if token_acc:
                    for t_fin in ["receivables", "payables"]:
                        dados_api = fetch_financeiro(token_acc, t_fin, data_ini, data_fim)
                        
                        # A API v2 retorna os dados dentro de uma lista ou objeto 'itens'
                        itens = dados_api if isinstance(dados_api, list) else dados_api.get("itens", [])
                        
                        if "erro" in dados_api:
                            erros_log.append(f"❌ {emp} ({t_fin}): {dados_api['msg']}")
                            continue

                        for item in itens:
                            valor = float(item.get('value') or item.get('amount') or 0)
                            tipo_label = 'Receita' if t_fin == "receivables" else 'Despesa'
                            multiplicador = 1 if t_fin == "receivables" else -1
                            
                            fluxo_data.append({
                                'Data': item['due_date'][:10],
                                'Empresa': emp,
                                'Tipo': tipo_label,
                                'Descrição': item.get('description', 'Sem descrição'),
                                'Valor': valor * multiplicador
                            })
                else:
                    erros_log.append(f"⚠️ {emp}: Falha ao renovar token.")
            except Exception as e:
                erros_log.append(f"❗ {emp}: Erro inesperado -> {str(e)}")

    if fluxo_data:
        df_final = pd.DataFrame(fluxo_data)
        df_final['Data'] = pd.to_datetime(df_final['Data'])
        
        # --- Dashboards ---
        c1, c2, c3 = st.columns(3)
        total_entradas = df_final[df_final['Valor'] > 0]['Valor'].sum()
        total_saidas = abs(df_final[df_final['Valor'] < 0]['Valor'].sum())
        
        c1.metric("Entradas", f"R$ {total_entradas:,.2f}")
        c2.metric("Saídas", f"R$ {total_saidas:,.2f}", delta_color="inverse")
        c3.metric("Saldo Líquido", f"R$ {(total_entradas - total_saidas):,.2f}")

        # Gráfico
        st.subheader("Visualização Temporal")
        df_agrupado = df_final.groupby('Data')['Valor'].sum()
        st.line_chart(df_agrupado)

        # Tabela Detalhada
        with st.expander("📄 Ver Lista Detalhada de Lançamentos"):
            df_exibicao = df_final.sort_values(by='Data')
            df_exibicao['Data'] = df_exibicao['Data'].dt.strftime('%d/%m/%Y')
            st.dataframe(df_exibicao, use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado encontrado para o período e empresa selecionados.")

    # Exibe erros de API apenas se houver
    if erros_log:
        with st.expander("⚠️ Log de Erros da API"):
            for erro in erros_log:
                st.write(erro)

# --- 6. CALLBACK DE AUTORIZAÇÃO (NOVA CONEXÃO) ---
if "code" in st.query_params and is_admin:
    st.divider()
    st.subheader("🔑 Configurar Nova Conexão")
    nome_empresa_nova = st.text_input("Digite o nome da Empresa como aparecerá no filtro:")
    
    if st.button("Finalizar Vínculo"):
        auth_code = st.query_params["code"]
        res = requests.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={"Authorization": f"Basic {B64_AUTH}", "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "authorization_code",
                "code": auth_code,
                "redirect_uri": REDIRECT_URI
            }
        )
        if res.status_code == 200:
            update_refresh_token(nome_empresa_nova, res.json().get("refresh_token"))
            st.success(f"Empresa '{nome_empresa_nova}' conectada com sucesso!")
            st.query_params.clear()
            st.rerun()
        else:
            st.error(f"Erro ao trocar código: {res.text}")
