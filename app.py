import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- CONFIGURAÇÕES DE PÁGINA ---
st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

# URLs da API Conta Azul
API_BASE_URL = "https://api-v2.contaazul.com"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"

# --- FUNÇÕES DE CONEXÃO ---

def get_sheet():
    """Conecta à planilha mestre de tokens."""
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro de conexão com Google Sheets: {e}")
        return None

def get_access_token(empresa_nome):
    """Renova o token para a empresa específica."""
    try:
        sh = get_sheet()
        cell = sh.find(empresa_nome)
        if not cell: return None
        
        refresh_token_atual = sh.cell(cell.row, 2).value
        auth_str = f"{st.secrets['conta_azul']['client_id']}:{st.secrets['conta_azul']['client_secret']}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        
        res = requests.post(TOKEN_URL, 
            headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": refresh_token_atual})

        if res.status_code == 200:
            token_data = res.json()
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
    except: return None
    return None

# --- INTERFACE (SIDEBAR) ---

with st.sidebar:
    st.title("🚀 BPO Financeiro")
    
    # Busca lista de empresas atualizada
    sh = get_sheet()
    if sh:
        df_sheet = pd.DataFrame(sh.get_all_records())
        lista_empresas = df_sheet['empresa'].unique().tolist() if not df_sheet.empty else []
    else:
        lista_empresas = []

    sel_empresa = st.selectbox("Filtrar Empresa", ["TODAS"] + lista_empresas)
    
    col_d1, col_d2 = st.columns(2)
    d_inicio = col_d1.date_input("Início", datetime.now() - timedelta(days=7))
    d_fim = col_d2.date_input("Fim", datetime.now() + timedelta(days=30))
    
    st.divider()
    
    # --- ACESSO LIBERADO: VINCULAR EMPRESAS ---
    with st.expander("🔗 Vincular/Gerenciar Empresas", expanded=False):
        nova_emp = st.text_input("Nome da Nova Empresa")
        novo_rt = st.text_input("Refresh Token Inicial", help="Obtido no primeiro acesso à API")
        if st.button("Salvar Vínculo"):
            if nova_emp and novo_rt and sh:
                sh.append_row([nova_emp, novo_rt])
                st.success(f"{nova_emp} vinculada com sucesso!")
                st.rerun()
            else:
                st.warning("Preencha todos os campos.")

    st.divider()
    debug_mode = st.checkbox("🔍 Modo Depuração", value=False)

# --- PROCESSAMENTO ---

if st.button("Sincronizar Dados", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados_totais = []
    logs = []

    for emp in alvos:
        token = get_access_token(emp)
        if not token:
            if debug_mode: logs.append(f"❌ {emp}: Falha no token")
            continue

        for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
            url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
            params = {
                "expiration_date_from": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                "expiration_date_to": d_fim.strftime('%Y-%m-%dT23:59:59Z')
            }
            res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            
            if debug_mode:
                logs.append({"Empresa": emp, "Tipo": tipo, "Status": res.status_code, "URL": res.url, "Response": res.text[:200]})

            if res.status_code == 200:
                for i in res.json():
                    dt = i.get('due_date') or i.get('expiration_date')
                    dados_totais.append({
                        'Empresa': emp,
                        'Data': pd.to_datetime(dt[:10]),
                        'Tipo': tipo,
                        'Valor': float(i.get('value', 0)),
                        'Descrição': i.get('description', 'S/D')
                    })

    # --- DASHBOARD ---
    if dados_totais:
        df = pd.DataFrame(dados_totais)
        
        # Métricas
        m1, m2, m3 = st.columns(3)
        rec = df[df['Tipo'] == 'Receber']['Valor'].sum()
        pag = df[df['Tipo'] == 'Pagar']['Valor'].sum()
        m1.metric("A Receber", f"R$ {rec:,.2f}")
        m2.metric("A Pagar", f"R$ {pag:,.2f}", delta_color="inverse")
        m3.metric("Saldo", f"R$ {(rec-pag):,.2f}")

        # Gráfico
        st.subheader("Fluxo por Dia")
        df_g = df.groupby(['Data', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        fig = go.Figure()
        if 'Receber' in df_g.columns: fig.add_trace(go.Bar(x=df_g['Data'], y=df_g['Receber'], name='Receber', marker_color='#00CC96'))
        if 'Pagar' in df_g.columns: fig.add_trace(go.Bar(x=df_g['Data'], y=-df_g['Pagar'], name='Pagar', marker_color='#EF553B'))
        fig.update_layout(barmode='relative', template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        # Tabela
        st.dataframe(df.sort_values('Data'), use_container_width=True)
    else:
        st.info("Nenhum lançamento encontrado.")

    if debug_mode and logs:
        with st.expander("Logs Técnicos"):
            for l in logs: st.json(l)
