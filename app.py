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

# Inicialização do tema (Padrão: Escuro)
if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

# URLs da API Conta Azul
API_BASE_URL = "https://api-v2.contaazul.com"
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"

# --- FUNÇÕES DE SUPORTE ---

def get_sheet():
    """Conecta à planilha do Google para buscar empresas e refresh_tokens."""
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
    # Abre a planilha pelo ID extraído da sua URL
    return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1

def get_access_token(empresa_nome):
    """Realiza o refresh do token OAuth2 conforme 'Autenticação na API da Conta Azul.docx'."""
    try:
        sh = get_sheet()
        cell = sh.find(empresa_nome)
        if not cell:
            return None
        
        refresh_token_atual = sh.cell(cell.row, 2).value
        
        # Header de autorização Basic (client_id:client_secret em base64)
        auth_str = f"{st.secrets['conta_azul']['client_id']}:{st.secrets['conta_azul']['client_secret']}"
        auth_header = base64.b64encode(auth_str.encode()).decode()
        
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token_atual
        }
        
        headers = {
            "Authorization": f"Basic {auth_header}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        response = requests.post(TOKEN_URL, headers=headers, data=payload)
        
        if response.status_code == 200:
            token_data = response.json()
            # Salva o novo refresh_token na planilha (importante: ele muda a cada uso)
            sh.update_cell(cell.row, 2, token_data['refresh_token'])
            return token_data['access_token']
        else:
            return None
    except Exception as e:
        return None

# --- INTERFACE (SIDEBAR) ---

with st.sidebar:
    st.title("⚙️ Painel de Controlo")
    
    try:
        df_sheet = pd.DataFrame(get_sheet().get_all_records())
        lista_empresas = df_sheet['empresa'].unique().tolist()
    except:
        lista_empresas = []
        st.error("Erro ao carregar lista de empresas da planilha.")

    sel_empresa = st.selectbox("Selecione a Empresa", ["TODAS"] + lista_empresas)
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        d_inicio = st.date_input("Data Início", datetime.now() - timedelta(days=7))
    with col_d2:
        d_fim = st.date_input("Data Fim", datetime.now() + timedelta(days=30))
    
    st.divider()
    # A variável abaixo controla se os logs aparecem ou não
    debug_mode = st.checkbox("🔍 Ativar Log de Depuração", value=False)

# --- LÓGICA PRINCIPAL ---

if st.button("🚀 Sincronizar Fluxo de Caixa", type="primary"):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados_totais = []
    logs_sessao = []

    with st.spinner(f"A processar {len(alvos)} empresa(s)..."):
        for emp in alvos:
            token = get_access_token(emp)
            if not token:
                if debug_mode: logs_sessao.append({"empresa": emp, "erro": "Falha na renovação do token"})
                continue

            # Endpoints corrigidos conforme a documentação 'Financeiro.docx'
            # Evitamos o '/eventos-financeiros/' que causava o erro 502/405
            rotas = [
                ("Receber", f"{API_BASE_URL}/v1/financeiro/contas-a-receber"),
                ("Pagar", f"{API_BASE_URL}/v1/financeiro/contas-a-pagar")
            ]

            for tipo, url in rotas:
                # Parâmetros de data no formato ISO exigido pela v2
                params = {
                    "expiration_date_from": d_inicio.strftime('%Y-%m-%dT00:00:00Z'),
                    "expiration_date_to": d_fim.strftime('%Y-%m-%dT23:59:59Z')
                }
                
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
                
                # Armazena logs apenas se solicitado
                if debug_mode:
                    logs_sessao.append({
                        "Empresa": emp,
                        "Fluxo": tipo,
                        "Status": res.status_code,
                        "URL_Chamada": res.url,
                        "Resposta_Raw": res.text[:250] # Limite para não poluir
                    })

                if res.status_code == 200:
                    items = res.json()
                    for i in items:
                        # Pega a data de vencimento (pode vir como due_date ou expiration_date)
                        dt_str = i.get('due_date') or i.get('expiration_date')
                        dados_totais.append({
                            'Empresa': emp,
                            'Data_Ref': pd.to_datetime(dt_str[:10]),
                            'Tipo': tipo,
                            'Valor': float(i.get('value', 0)),
                            'Descritivo': i.get('description', i.get('memo', 'Sem descrição')),
                            'Status': i.get('status', 'Pendente')
                        })

    # --- EXIBIÇÃO DOS DADOS ---
    
    if dados_totais:
        df_final = pd.DataFrame(dados_totais)
        
        # Cards de Resumo
        c1, c2, c3 = st.columns(3)
        v_receber = df_final[df_final['Tipo'] == 'Receber']['Valor'].sum()
        v_pagar = df_final[df_final['Tipo'] == 'Pagar']['Valor'].sum()
        
        c1.metric("Total a Receber", f"R$ {v_receber:,.2f}")
        c2.metric("Total a Pagar", f"R$ {v_pagar:,.2f}", delta_color="inverse")
        c3.metric("Saldo do Período", f"R$ {(v_receber - v_pagar):,.2f}")

        # Gráfico Comparativo
        st.subheader("Evolução Financeira Diária")
        df_graph = df_final.groupby(['Data_Ref', 'Tipo'])['Valor'].sum().unstack(fill_value=0).reset_index()
        
        fig = go.Figure()
        if 'Receber' in df_graph.columns:
            fig.add_trace(go.Bar(x=df_graph['Data_Ref'], y=df_graph['Receber'], name='Receber', marker_color='#2ecc71'))
        if 'Pagar' in df_graph.columns:
            fig.add_trace(go.Bar(x=df_graph['Data_Ref'], y=-df_graph['Pagar'], name='Pagar', marker_color='#e74c3c'))
        
        fig.update_layout(barmode='relative', template="plotly_dark" if IS_DARK else "plotly_white")
        st.plotly_chart(fig, use_container_width=True)

        # Tabela Detalhada
        st.subheader("Lista de Lançamentos")
        st.dataframe(
            df_final.sort_values(by='Data_Ref'), 
            use_container_width=True, 
            column_config={
                "Data_Ref": st.column_config.DateColumn("Vencimento"),
                "Valor": st.column_config.NumberColumn("Valor (R$)", format="%.2f")
            }
        )
    else:
        st.info("Nenhum dado encontrado para o período selecionado.")

    # --- ÁREA DE DEPURAÇÃO (SÓ APARECE SE O BOTÃO NO SIDEBAR FOR ATIVADO) ---
    if debug_mode and logs_sessao:
        st.divider()
        with st.expander("🛠️ Detalhes da Depuração (API)", expanded=True):
            for log in logs_sessao:
                st.write(f"**Empresa:** {log.get('Empresa', 'N/A')} | **Status:** {log.get('Status')}")
                st.json(log)
