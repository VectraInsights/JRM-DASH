import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="BPO Dashboard - JRM", layout="wide")

CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]
TOKEN_URL = "https://auth.contaazul.com/oauth2/token"
API_BASE_URL = "https://api.contaazul.com"

# --- INFRAESTRUTURA ---

def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_sheets"]), scope)
        return gspread.authorize(creds).open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0").sheet1
    except Exception as e:
        st.error(f"Erro na planilha: {e}")
        return None

def update_tokens_in_sheet(empresa, novo_rt):
    sh = get_sheet()
    if not sh: return
    empresa_busca = empresa.strip().upper()
    try:
        col_empresas = sh.col_values(1) 
        idx = -1
        for i, nome in enumerate(col_empresas):
            if nome.strip().upper() == empresa_busca:
                idx = i + 1
                break
        
        if idx > 0:
            sh.update_cell(idx, 2, novo_rt)
            st.toast(f"✅ Token de '{empresa}' atualizado na planilha!")
        else:
            sh.append_row([empresa, novo_rt])
            st.toast(f"✨ '{empresa}' cadastrada com sucesso!")
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

def get_valid_access_token(empresa_nome):
    """Renova o token e já atualiza a planilha."""
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(empresa_nome)
        rt_atual = sh.cell(cell.row, 2).value
    except:
        return None

    auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    res = requests.post(TOKEN_URL, 
        headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": rt_atual})

    if res.status_code == 200:
        dados = res.json()
        update_tokens_in_sheet(empresa_nome, dados['refresh_token'])
        return dados['access_token']
    return None

# --- INTERFACE (SIDEBAR) ---

with st.sidebar:
    st.header("🔗 Conexão Conta Azul")
    
    url_auth = f"https://auth.contaazul.com/login?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&scope=openid+profile+aws.cognito.signin.user.admin"
    st.link_button("🔑 Vincular Nova Empresa", url_auth, type="primary", use_container_width=True)
    
    params = st.query_params
    if "code" in params:
        st.divider()
        st.info("🔄 Finalize o registro:")
        nome_vinc = st.text_input("Nome exato da Empresa", placeholder="Ex: JTL")
        if st.button("Confirmar e Salvar"):
            auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            res = requests.post(TOKEN_URL, 
                headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
                data={"grant_type": "authorization_code", "code": params["code"], "redirect_uri": REDIRECT_URI})
            
            if res.status_code == 200:
                update_tokens_in_sheet(nome_vinc, res.json()['refresh_token'])
                st.success("Vinculado! Limpando acesso...")
                st.query_params.clear()
                st.rerun()
            else:
                st.error("Erro na autorização.")

    st.divider()
    st.header("📊 Filtros")
    sh = get_sheet()
    lista_empresas = pd.DataFrame(sh.get_all_records())['empresa'].unique().tolist() if sh else []
    sel_empresa = st.selectbox("Empresa", ["TODAS"] + lista_empresas)
    d_inicio = st.date_input("Início", datetime.now() - timedelta(days=7))
    d_fim = st.date_input("Fim", datetime.now() + timedelta(days=30))

# --- DASHBOARD ---

if st.button("🚀 Sincronizar Dashboard", type="primary", use_container_width=True):
    alvos = lista_empresas if sel_empresa == "TODAS" else [sel_empresa]
    dados_fin = []
    
    for emp in alvos:
        with st.status(f"Sincronizando {emp}...", expanded=False) as status:
            # PASSO 1: Pega um token novo uma única vez para esta empresa
            token = get_valid_access_token(emp)
            
            if not token:
                st.warning(f"⚠️ Token inválido para {emp}. Refaça o vínculo.")
                continue
            
            # PASSO 2: Usa o mesmo token para ambas as requisições
            for tipo, endpoint in [("Receber", "contas-a-receber"), ("Pagar", "contas-a-pagar")]:
                url = f"{API_BASE_URL}/v1/financeiro/{endpoint}"
                params_api = {
                    "data_vencimento_de": d_inicio.strftime('%Y-%m-%d'),
                    "data_vencimento_ate": d_fim.strftime('%Y-%m-%d')
                }
                
                res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params_api)
                
                with st.expander(f"🔍 Debug: {emp} - {tipo}"):
                    st.write(f"Status: {res.status_code}")
                    st.json(res.json())

                if res.status_code == 200:
                    for i in res.json().get('itens', []):
                        dados_fin.append({
                            'Empresa': emp,
                            'Data': i.get('data_vencimento')[:10],
                            'Tipo': tipo,
                            'Valor': float(i.get('valor', 0)),
                            'Descrição': i.get('descricao', 'S/D')
                        })
            
            status.update(label=f"{emp} Concluído!", state="complete")

    if dados_fin:
        df = pd.DataFrame(dados_fin)
        c1, c2, c3 = st.columns(3)
        rec = df[df['Tipo'] == 'Receber']['Valor'].sum()
        pag = df[df['Tipo'] == 'Pagar']['Valor'].sum()
        
        c1.metric("A Receber", f"R$ {rec:,.2f}")
        c2.metric("A Pagar", f"R$ {pag:,.2f}", delta_color="inverse")
        c3.metric("Líquido", f"R$ {(rec - pag):,.2f}")
        
        st.divider()
        st.dataframe(df.sort_values('Data'), use_container_width=True)
    else:
        st.info("Nenhum dado encontrado.")
