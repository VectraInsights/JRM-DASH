import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
from datetime import datetime, timedelta
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. CONFIGURAÇÕES E ESTILO ---
st.set_page_config(page_title="Fluxo de Caixa JRM", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        /* Limpeza de elementos nativos */
        .stAppDeployButton, [data-testid="stDeployButton"],
        [data-testid="stToolbarActionButtonIcon"],
        button[data-testid="stBaseButton-header"],
        [data-testid="stViewerBadge"], footer {
            display: none !important;
        }

        /* CARDS ADAPTÁVEIS (DYNAMIC THEME) */
        .card-container {
            /* Usa as cores do tema do Streamlit: Fundo secundário e texto principal */
            background-color: var(--secondary-background-color); 
            color: var(--text-color);
            padding: 20px;
            border-radius: 12px;
            border-left: 5px solid #34495e;
            box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 10px;
        }
        
        .card-title {
            font-size: 14px;
            /* Opacidade para o título ficar discreto mas legível em ambos os temas */
            opacity: 0.7;
            margin-bottom: 5px;
            font-weight: 500;
        }
        
        .card-value {
            font-size: 26px;
            font-weight: bold;
        }

        /* Cores de borda fixas para manter a identidade visual */
        .border-receber { border-left-color: #2ecc71 !important; }
        .border-pagar { border-left-color: #e74c3c !important; }
        .border-saldo { border-left-color: #3498db !important; }

    </style>
""", unsafe_allow_html=True)

# --- 2. FUNÇÕES DE APOIO ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_info = st.secrets["google_sheets"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        # URL da planilha do Victor Leandro Gomes Soares
        return client.open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na conexão: {e}")
        return None

def format_br(valor):
    # Formatação DD/MM/AAAA conforme solicitado nas correções
    return f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

def obter_token(empresa_nome):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt = sh.cell(cell.row, 2).value
        ca = st.secrets["conta_azul"]
        auth_b64 = base64.b64encode(f"{ca['client_id']}:{ca['client_secret']}".encode()).decode()
        res = requests.post("https://auth.contaazul.com/oauth2/token", 
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": rt})
        if res.status_code == 200:
            dados = res.json()
            if dados.get('refresh_token'): sh.update_cell(cell.row, 2, dados['refresh_token'])
            return dados['access_token']
    except: pass
    return None

def buscar_v2(endpoint, token, params):
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1})
    while True:
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        itens = res.json().get('itens', [])
        if not itens: break
        for i in itens:
            saldo = i.get('total', 0) - i.get('pago', 0)
            if saldo > 0:
                itens_acumulados.append({"Vencimento": i.get("data_vencimento"), "Valor": saldo})
        if len(itens) < 100: break
        params["pagina"] += 1
    return itens_acumulados

# --- 3. PROCESSO DE SINCRONIZAÇÃO (PARA LOOKER STUDIO) ---

# 1. Definimos um período amplo para o Looker ter histórico (ex: 30 dias atrás até 60 dias à frente)
hoje = datetime.now().date()
data_ini = hoje - timedelta(days=30)
data_fim = hoje + timedelta(days=60)

# 2. Buscamos a lista de todos os clientes na Planilha
sh_client = get_sheet()
clientes = [r[0] for r in sh_client.get_all_values()[1:]] if sh_client else []

p_total, r_total = [], []

# 3. Loop de coleta de dados da API da Conta Azul
for emp in clientes:
    tk = obter_token(emp)
    if tk:
        api_params = {"data_vencimento_de": data_ini.isoformat(), "data_vencimento_ate": data_fim.isoformat()}
        
        # Buscamos os dados e adicionamos o nome da empresa para filtrar no Looker
        pagar = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", tk, api_params.copy())
        receber = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", tk, api_params.copy())
        
        for item in pagar: item.update({"Empresa": emp, "Tipo": "Despesa"})
        for item in receber: item.update({"Empresa": emp, "Tipo": "Receita"})
        
        p_total.extend(pagar)
        r_total.extend(receber)

# 4. Consolidação dos dados em um DataFrame
if p_total or r_total:
    df_looker = pd.DataFrame(p_total + r_total)
    
    # Organiza as colunas para o Looker Studio
    df_looker = df_looker[['Vencimento', 'Empresa', 'Tipo', 'Valor']]
    
    # 5. SALVAR NA PLANILHA (Aba: Base_Looker)
    try:
        # Tenta abrir a aba, se não existir, cria
        try:
            worksheet = sh_client.spreadsheet.worksheet("Base_Looker")
        except:
            worksheet = sh_client.spreadsheet.add_worksheet(title="Base_Looker", rows="5000", cols="5")
        
        # Limpa e atualiza com os dados novos
        worksheet.clear()
        # Prepara os dados: Cabeçalho + Valores
        dados_finais = [df_looker.columns.values.tolist()] + df_looker.astype(str).values.tolist()
        worksheet.update(dados_finais)
        
        print(f"Sucesso! {len(df_looker)} linhas enviadas para o Looker Studio.")
    except Exception as e:
        print(f"Erro ao salvar na planilha: {e}")
