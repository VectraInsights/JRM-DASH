import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go
import time

# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

BG_COLOR    = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
TEXT_COLOR  = "#ffffff"  if st.session_state.theme == 'dark' else "#31333F"
INPUT_BG    = "#1e1e1e"  if st.session_state.theme == 'dark' else "#f0f2f6"
BORDER      = "#444"     if st.session_state.theme == 'dark' else "#ccc"
PLOTLY_TPL  = "plotly_dark" if st.session_state.theme == 'dark' else "plotly_white"

# --- 2. CSS ---
st.markdown(f"""
<style>
    header {{visibility: hidden;}}
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_COLOR}; }}

    div[data-testid="stDateInput"] > div {{
        background-color: transparent !important;
        border: none !important;
    }}
    div[data-testid="stDateInput"] div,
    div[data-testid="stDateInput"] input {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
        border-radius: 8px !important;
    }}
    div[data-baseweb="popover"] {{
        background-color: {BG_COLOR} !important;
        border: 1px solid {BORDER};
    }}
    div[data-baseweb="calendar"] {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
    }}
    div[data-baseweb="select"] > div {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
    }}
    [data-testid="stMetricValue"] {{ color: {TEXT_COLOR} !important; }}
</style>
""", unsafe_allow_html=True)

# Botão de tema no topo (coluna)
col_titulo, col_tema = st.columns([10, 1])
with col_titulo:
    st.title("📊 Fluxo de Caixa BPO")
with col_tema:
    st.write("")
    if st.button("🌓", help="Alternar tema"):
        st.session_state.theme = 'light' if st.session_state.theme == 'dark' else 'dark'
        st.rerun()

# --- 3. CREDENCIAIS ---
CLIENT_ID     = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI  = st.secrets["conta_azul"]["redirect_uri"]
PLANILHA_URL  = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
B64_AUTH      = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

TOKEN_URL = "https://auth.contaazul.com/oauth2/token"

# --- 4. GOOGLE SHEETS (SEM CACHE para garantir dados frescos) ---
def get_sheet():
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(
        dict(st.secrets["google_sheets"]), scope
    )
    client = gspread.authorize(creds)
    return client.open_by_url(PLANILHA_URL).sheet1

def listar_empresas():
    try:
        sh = get_sheet()
        records = sh.get_all_records()
        df = pd.DataFrame(records)
        return df['empresa'].dropna().unique().tolist() if not df.empty else []
    except Exception as e:
        st.sidebar.error(f"Erro ao ler planilha: {e}")
        return []

def get_access_token(empresa_nome):
    try:
        sh = get_sheet()
        cell = sh.find(empresa_nome)
        if not cell:
            return None
        rt = sh.cell(cell.row, 2).value
        if not rt:
            st.warning(f"Sem refresh_token para '{empresa_nome}'")
            return None

        res = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {B64_AUTH}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt}
        )

        if res.status_code == 200:
            token_data = res.json()
            # Atualiza o refresh_token na planilha
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
        else:
            st.error(f"Erro ao renovar token de '{empresa_nome}': {res.status_code} - {res.text}")
            return None
    except Exception as e:
        st.error(f"Exceção ao obter token de '{empresa_nome}': {e}")
        return None

# --- 5. BARRA LATERAL ---
with st.sidebar:
    st.title("Filtros")
    lista_empresas = listar_empresas()
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("Início", datetime.now(), format="DD/MM/YYYY")
    d_fim    = st.date_input("Fim", datetime.now() + timedelta(days=30), format="DD/MM/YYYY")

    st.markdown("<br>" * 8, unsafe_allow_html=True)
    st.divider()
    # Checkbox invisível para Modo ADM
    modo_adm = st.checkbox("", label_visibility="collapsed", key="adm_check")

# --- 6. LEITURA DE QUERY PARAMS (compatível com Streamlit ≥ 1.30) ---
params = st.query_params.to_dict()

# --- 7. PAINEL ADM ---
if modo_adm or "code" in params:
    with st.container(border=True):
        st.subheader("🔐 Gestão de Empresas")

        if "code" in params:
            st.success("✅ Autorização recebida! Preencha o nome e salve.")
            nome_nova = st.text_input("Nome da empresa:", key="input_nome_empresa")

            if st.button("Gravar Empresa na Planilha", type="primary"):
                if nome_nova.strip():
                    with st.spinner("Convertendo código em token..."):
                        resp = requests.post(
                            TOKEN_URL,
                            headers={"Authorization": f"Basic {B64_AUTH}",
                                     "Content-Type": "application/x-www-form-urlencoded"},
                            data={
                                "grant_type":   "authorization_code",
                                "code":         params["code"],
                                "redirect_uri": REDIRECT_URI
                            }
                        )
                    if resp.status_code == 200:
                        data = resp.json()
                        get_sheet().append_row([nome_nova.strip(), data['refresh_token']])
                        st.success(f"✅ Empresa '{nome_nova}' cadastrada com sucesso!")
                        time.sleep(2)
                        st.query_params.clear()
                        st.rerun()
                    else:
                        st.error(f"Erro {resp.status_code}: {resp.text}")
                        st.info("O código de autorização expira em ~1 min. Reconecte se necessário.")
                else:
                    st.warning("Digite um nome para a empresa.")

        else:
            pwd = st.text_input("Senha Master", type="password", key="senha_adm")
            if pwd == st.secrets.get("master_password", "8429coconoiaKc#"):
                url_ca = (
                    f"https://auth.contaazul.com/login"
                    f"?response_type=code"
                    f"&client_id={CLIENT_ID}"
                    f"&redirect_uri={REDIRECT_URI}"
                    f"&scope=openid+profile+aws.cognito.signin.user.admin"
                )
                st.link_button("🔌 Conectar Nova Empresa", url_ca)
            elif pwd:
                st.error("Senha incorreta.")

# --- 8. CONSULTA E GRÁFICOS ---
if st.button("🚀 Consultar Fluxo de Caixa", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]

    if not alvos:
        st.warning("Nenhuma empresa cadastrada.")
        st.stop()

    all_data = []
    erros    = []

    with st.spinner("Consultando APIs..."):
        for emp in alvos:
            tk = get_access_token(emp)
            if not tk:
                erros.append(emp)
                continue

            # ----- Endpoint correto do Conta Azul v1 -----
            # Recebíveis
            for tipo, endpoint in [
                ("Receber", "https://api.contaazul.com/v1/receivables"),
                ("Pagar",   "https://api.contaazul.com/v1/payables"),
            ]:
                page = 0
                while True:
                    res = requests.get(
                        endpoint,
                        headers={"Authorization": f"Bearer {tk}"},
                        params={
                            "emission_start": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                            "emission_end":   d_fim.strftime('%Y-%m-%dT23:59:59Z'),
                            "page_size": 200,
                            "page":      page,
                        }
                    )
                    if res.status_code != 200:
                        erros.append(f"{emp}/{tipo}: {res.status_code}")
                        break

                    items = res.json() if isinstance(res.json(), list) else res.json().get('items', [])
                    if not items:
                        break

                    for l in items:
                        # Tenta diferentes nomes de campo conforme versão da API
                        data_ref = l.get('due_date') or l.get('emission') or l.get('competence')
                        valor    = l.get('value') or l.get('amount') or 0
                        all_data.append({
                            'Empresa': emp,
                            'Data':    pd.to_datetime(data_ref[:10]),
                            'Tipo':    tipo,
                            'Valor':   float(valor),
                            'Status':  l.get('status', ''),
                        })

                    # Paginação: para se vieram menos que page_size
                    if len(items) < 200:
                        break
                    page += 1

    if erros:
        st.warning(f"Erros em: {', '.join(erros)}")

    if not all_data:
        st.info("Nenhum lançamento encontrado para os filtros selecionados.")
        st.stop()

    df = pd.DataFrame(all_data)

    # --- Métricas ---
    total_rec  = df[df['Tipo'] == 'Receber']['Valor'].sum()
    total_pag  = df[df['Tipo'] == 'Pagar']['Valor'].sum()
    saldo      = total_rec - total_pag

    c1, c2, c3 = st.columns(3)
    c1.metric("💚 A Receber",    f"R$ {total_rec:,.2f}")
    c2.metric("🔴 A Pagar",      f"R$ {total_pag:,.2f}")
    c3.metric("🔵 Saldo Período",f"R$ {saldo:,.2f}",
              delta=f"R$ {saldo:,.2f}", delta_color="normal")

    # --- Agrupamento diário ---
    df_resumo = (
        df.groupby(['Data', 'Tipo'])['Valor']
        .sum()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ['Receber', 'Pagar']:
        if col not in df_resumo.columns:
            df_resumo[col] = 0.0

    df_resumo['Saldo']     = df_resumo['Receber'] - df_resumo['Pagar']
    df_resumo['Acumulado'] = df_resumo['Saldo'].cumsum()

    # --- Gráfico ---
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df_resumo['Data'], y=df_resumo['Receber'],
        name='Receber', marker_color='#00CC96'
    ))
    fig.add_trace(go.Bar(
        x=df_resumo['Data'], y=-df_resumo['Pagar'],
        name='Pagar', marker_color='#EF553B'
    ))
    fig.add_trace(go.Scatter(
        x=df_resumo['Data'], y=df_resumo['Acumulado'],
        name='Saldo Acumulado',
        line=dict(color='#636EFA', width=3)
    ))
    fig.update_layout(
        barmode='relative',
        template=PLOTLY_TPL,
        xaxis_title="Data",
        yaxis_title="R$",
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Tabela ---
    df_tab = df_resumo.copy()
    df_tab['Data'] = df_tab['Data'].dt.strftime('%d/%m/%Y')
    df_tab = df_tab.rename(columns={
        'Receber': 'A Receber (R$)',
        'Pagar':   'A Pagar (R$)',
        'Saldo':   'Saldo Dia (R$)',
        'Acumulado': 'Acumulado (R$)'
    })
    st.dataframe(
        df_tab.style.format({
            'A Receber (R$)':  'R$ {:,.2f}',
            'A Pagar (R$)':    'R$ {:,.2f}',
            'Saldo Dia (R$)':  'R$ {:,.2f}',
            'Acumulado (R$)':  'R$ {:,.2f}',
        }),
        use_container_width=True,
        hide_index=True
    )

    # Detalhe por empresa (se "TODAS")
    if sel_empresa == "TODAS":
        st.subheader("Por Empresa")
        df_emp = df.groupby(['Empresa', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        st.dataframe(df_emp, use_container_width=True, hide_index=True)
