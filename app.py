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
            box-shadow: none !important; font-size: 18px !important;
            margin: 0 !important;
        }}
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap: 0rem; }}
    </style>
    """, unsafe_allow_html=True)

# --- 2. API & GOOGLE SHEETS ---
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

# --- 3. FLUXO DE CAPTURA (RENOMEAR NA HORA) ---
query_params = st.query_params
if "code" in query_params:
    st.warning("📥 Nova conexão detectada!")
    with st.form("save_empresa"):
        nome_emp = st.text_input("Nome da Empresa para salvar:")
        if st.form_submit_button("Confirmar Registro"):
            res = requests.post("https://auth.contaazul.com/oauth2/token", 
                                headers={"Authorization": f"Basic {B64_AUTH}"}, 
                                data={"grant_type": "authorization_code", "code": query_params["code"], "redirect_uri": REDIRECT_URI})
            if res.status_code == 200:
                rt = res.json().get("refresh_token")
                sheet = get_sheet()
                try:
                    cell = sheet.find(nome_emp)
                    sheet.update_cell(cell.row, 2, rt)
                except:
                    sheet.append_row([nome_emp, rt])
                st.query_params.clear()
                st.rerun()

# --- 4. SIDEBAR ---
if 'adm_mode' not in st.session_state: st.session_state.adm_mode = False

with st.sidebar:
    st.subheader("Filtros")
    df_db = pd.DataFrame(get_sheet().get_all_records())
    empresas = df_db['empresa'].unique().tolist() if not df_db.empty else []
    selecao = st.selectbox("Empresa", ["TODAS"] + empresas)
    d_ini = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=7), format="DD/MM/YYYY")
    
    st.markdown("<br>" * 10, unsafe_allow_html=True)
    st.divider()
    c1, c2, _ = st.columns([0.15, 0.15, 0.7])
    with c1:
        if st.button("👁️" if st.session_state.adm_mode else "👁️‍🗨️"):
            st.session_state.adm_mode = not st.session_state.adm_mode
            st.rerun()
    with c2:
        if st.button("🌓"):
            st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
            st.rerun()

# --- 5. CONSULTA E PROCESSAMENTO ---
st.title("📊 Fluxo de Caixa BPO")

if st.session_state.adm_mode:
    with st.expander("🔐 Configurações"):
        if st.text_input("Senha ADM", type="password") == "8429coconoiaKc#":
            st.link_button("🔗 Conectar Nova Empresa", f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}")

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    debug_info = None
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
                
                itens = res.get("itens", [])
                for i in itens:
                    # TENTA TODAS AS CHAVES POSSÍVEIS DE VALOR
                    v = (i.get('valor') or i.get('valor_total') or i.get('valor_parcela') or 
                         i.get('amount') or i.get('value') or i.get('total') or 0.0)
                    
                    if v == 0 and not debug_info: 
                        debug_info = i # Captura um exemplo se vier zerado
                    
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

        # Gráfico
        df_plot = df.groupby([df['Data'].dt.strftime('%d/%m'), 'Tipo'])['Valor'].sum().reset_index()
        fig = px.bar(df_plot, x='Data', y='Valor', color='Tipo', barmode='group',
                     color_discrete_map={'Receita': '#00CC96', 'Despesa': '#EF553B'},
                     template="plotly_dark" if st.session_state.theme == 'dark' else "plotly_white")
        st.plotly_chart(fig, use_container_width=True)

        # Tabela (Sem índice e Data Limpa)
        df_table = df.copy()
        df_table['Data'] = df_table['Data'].dt.strftime('%d/%m/%Y')
        df_table['Valor'] = df_table['Valor'].map('R$ {:,.2f}'.format)
        st.dataframe(df_table.sort_values('Data'), use_container_width=True, hide_index=True)
        
        if debug_info and rec == 0:
            with st.expander("🛠️ Depuração de Dados (O valor veio zero)"):
                st.write("A API enviou estes campos. Procure onde está o valor real:")
                st.json(debug_info)
    else:
        st.error("Nenhum dado encontrado. Verifique se os tokens das empresas estão válidos no modo ADM.")
