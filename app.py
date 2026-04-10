import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.express as px

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state: st.session_state.theme = 'dark'

bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "white" if st.session_state.theme == 'dark' else "black"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        [data-testid="stSidebar"] button {{
            border: none !important; background: transparent !important;
            padding: 0 !important; width: auto !important;
            box-shadow: none !important; font-size: 20px !important;
        }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. CONFIGURAÇÕES API & GOOGLE SHEETS ---
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
B64_AUTH = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

@st.cache_resource
def get_sheet():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
    return gspread.authorize(creds).open_by_url(PLANILHA_URL).sheet1

def refresh_access_token(refresh_token):
    url = "https://auth.contaazul.com/oauth2/token"
    res = requests.post(url, headers={"Authorization": f"Basic {B64_AUTH}"}, data={"grant_type": "refresh_token", "refresh_token": refresh_token})
    return res.json().get("access_token") if res.status_code == 200 else None

# --- 3. FLUXO DE CAPTURA E NOMEAÇÃO ---
query_params = st.query_params
if "code" in query_params:
    st.info("⚡ Conexão detectada! Como deseja salvar esta empresa?")
    with st.form("form_novo_token"):
        auth_code = query_params["code"]
        # Tenta pegar o nome oficial da Conta Azul como sugestão
        nome_sugerido = "Nova Empresa"
        
        nome_final = st.text_input("Nome da Empresa (para exibição no Dashboard)", value=nome_sugerido)
        submit = st.form_submit_button("Confirmar e Salvar")
        
        if submit:
            url_token = "https://auth.contaazul.com/oauth2/token"
            data = {"grant_type": "authorization_code", "code": auth_code, "redirect_uri": REDIRECT_URI}
            res = requests.post(url_token, headers={"Authorization": f"Basic {B64_AUTH}"}, data=data)
            
            if res.status_code == 200:
                refresh_t = res.json().get("refresh_token")
                sheet = get_sheet()
                # Verifica se já existe para atualizar ou criar nova linha
                celula = None
                try: celula = sheet.find(nome_final)
                except: pass
                
                if celula:
                    sheet.update_cell(celula.row, 2, refresh_t)
                    st.success(f"✅ Token de '{nome_final}' atualizado!")
                else:
                    sheet.append_row([nome_final, refresh_t])
                    st.success(f"✅ '{nome_final}' cadastrada com sucesso!")
                
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Erro na troca do código. Tente novamente.")

# --- 4. SIDEBAR ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now())
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=15))
    
    st.markdown("<br>" * 8, unsafe_allow_html=True)
    st.divider()
    c1, c2, _ = st.columns([0.2, 0.2, 0.6])
    with c1:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️"):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with c2:
        if st.button("🌓"):
            st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
            st.rerun()

# --- 5. EXECUÇÃO E GRÁFICOS ---
st.title("📊 Fluxo de Caixa BPO")

if st.session_state.adm_mode:
    with st.expander("🔐 Área ADM"):
        if st.text_input("Chave", type="password") == "8429coconoiaKc#":
            st.link_button("🔗 Conectar/Atualizar Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_proc = empresas if selecao == "TODAS" else [selecao]
    
    for emp in lista_proc:
        row = df_db[df_db['empresa'] == emp].iloc[0]
        token = refresh_access_token(row['refresh_token'])
        
        if token:
            for t in ["receivables", "payables"]:
                slug = 'contas-a-receber' if t=='receivables' else 'contas-a-pagar'
                url = f"https://api-v2.contaazul.com/v1/financeiro/eventos-financeiros/{slug}/buscar"
                params = {"data_vencimento_de": d_ini.strftime('%Y-%m-%d'), "data_vencimento_ate": d_fim.strftime('%Y-%m-%d')}
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params).json()
                
                for i in res.get("itens", []):
                    # Captura de valor robusta (tentando várias chaves da v2)
                    v = i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 0
                    dt = i.get('data_vencimento') or i.get('due_date')
                    data_points.append({
                        'Data': pd.to_datetime(dt),
                        'Empresa': emp,
                        'Tipo': 'Receita' if t=='receivables' else 'Despesa',
                        'Valor': float(v)
                    })
    
    if data_points:
        df = pd.DataFrame(data_points)
        
        # Métricas
        m1, m2, m3 = st.columns(3)
        rec = df[df['Tipo'] == 'Receita']['Valor'].sum()
        des = df[df['Tipo'] == 'Despesa']['Valor'].sum()
        m1.metric("Entradas", f"R$ {rec:,.2f}")
        m2.metric("Saídas", f"R$ {des:,.2f}")
        m3.metric("Saldo Líquido", f"R$ {(rec - des):,.2f}")

        # Gráfico de Barras (Fluxo por Dia)
        df_agrupado = df.groupby([df['Data'].dt.strftime('%d/%m'), 'Tipo'])['Valor'].sum().reset_index()
        fig = px.bar(df_agrupado, x='Data', y='Valor', color='Tipo', barmode='group',
                     color_discrete_map={'Receita': '#00CC96', 'Despesa': '#EF553B'},
                     template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white")
        st.plotly_chart(fig, use_container_width=True)

        # Tabela Detalhada (Sem índice, Data limpa)
        st.subheader("📄 Lançamentos Detalhados")
        df_tabela = df.copy()
        df_tabela['Data'] = df_tabela['Data'].dt.strftime('%d/%m/%Y')
        st.dataframe(df_tabela.sort_values('Data'), use_container_width=True, hide_index=True)
    else:
        st.warning("Nenhum dado financeiro encontrado no período selecionado.")
