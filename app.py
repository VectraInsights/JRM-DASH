import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES DE API E PLANILHA ---
URL_PLANILHA = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit?gid=0#gid=0"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    """Conecta ao Google Sheets tratando a chave privada para evitar erro de PEM."""
    try:
        # 1. Busca os dados do Secrets
        info = dict(st.secrets["connections"]["gsheets"])
        
        # 2. Sanitização da Private Key (Onde dava o erro InvalidByte)
        pk = info["private_key"].strip()
        
        # Converte \n literais em quebras reais e remove espaços em branco de cada linha
        # Isso corrige o erro no byte 1629 (o sinal de "=")
        linhas_limpas = [linha.strip() for linha in pk.replace("\\n", "\n").split('\n')]
        pk_formatada = '\n'.join(linhas_limpas)
        
        # Garante que o cabeçalho e rodapé PEM estejam isolados por quebras de linha
        if "-----BEGIN PRIVATE KEY-----" in pk_formatada and not pk_formatada.startswith("-----BEGIN PRIVATE KEY-----\n"):
            pk_formatada = pk_formatada.replace("-----BEGIN PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\n")
        if "-----END PRIVATE KEY-----" in pk_formatada and "\n-----END PRIVATE KEY-----" not in pk_formatada:
            pk_formatada = pk_formatada.replace("-----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----")
            
        info["private_key"] = pk_formatada
        
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Autenticação nativa do Google
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        return client.open_by_url(URL_PLANILHA).sheet1
        
    except Exception as e:
        st.error(f"❌ Erro Crítico na Conexão Google: {e}")
        st.stop()

def obter_access_token(empresa, refresh_token, aba_planilha):
    """Renova o token na Conta Azul e salva o novo na planilha automaticamente."""
    url = "https://auth.contaazul.com/oauth2/token"
    payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    try:
        response = requests.post(url, auth=(CLIENT_ID, CLIENT_SECRET), data=payload)
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            
            # Localiza a empresa na Coluna A e atualiza o token na Coluna B (col + 1)
            cell = aba_planilha.find(empresa)
            aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            
            return dados.get("access_token")
        return None
    except:
        return None

def listar_lancamentos(access_token):
    """Busca as transações financeiras dos últimos 30 dias."""
    url = "https://api.contaazul.com/v1/financials/transactions"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "expiration_start": (datetime.now() - timedelta(days=30)).date().isoformat(),
        "expiration_end": datetime.now().date().isoformat()
    }
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            res = r.json()
            # Retorna lista de itens ou lista vazia
            return res if isinstance(res, list) else res.get('items', [])
        return []
    except:
        return []

# --- INTERFACE STREAMLIT ---
st.set_page_config(page_title="Dashboard BPO JRM", layout="wide")
st.title("🏢 Dashboard Multi-CNPJ Consolidado")

if st.button('🚀 Sincronizar Todas as Empresas'):
    aba = conectar_google_sheets()
    
    with st.status("Sincronizando com Conta Azul...", expanded=True) as status:
        try:
            # Lê os tokens atuais da aba principal
            dados_planilha = aba.get_all_records()
            df_tokens = pd.DataFrame(dados_planilha)
        except Exception as e:
            st.error(f"Erro ao ler a planilha: {e}")
            st.stop()

        todos_dados = []
        for i, row in df_tokens.iterrows():
            empresa = row['empresa']
            st.write(f"Processando: **{empresa}**...")
            
            # Tenta renovar o token e buscar dados
            acc_token = obter_access_token(empresa, row['refresh_token'], aba)
            
            if acc_token:
                importados = listar_lancamentos(acc_token)
                for item in importados:
                    item['origem_empresa'] = empresa
                    # Garante que o valor seja numérico para cálculos
                    item['valor_total'] = float(item.get('value', 0))
                todos_dados.extend(importados)
            else:
                st.warning(f"⚠️ {empresa}: Falha na renovação do token. Verifique a planilha.")
        
        status.update(label="Sincronização concluída!", state="complete", expanded=False)

    if todos_dados:
        df_final = pd.DataFrame(todos_dados)
        st.success(f"✅ Sucesso! {len(df_final)} lançamentos importados.")
        
        # Exibição do Dashboard
        st.subheader("Extrato Consolidado")
        st.dataframe(df_final, use_container_width=True)
        
        # Exemplo de Resumo por Empresa
        st.subheader("Resumo por Empresa")
        resumo = df_final.groupby('origem_empresa')['valor_total'].sum().reset_index()
        st.table(resumo)
    else:
        st.error("Nenhum dado foi coletado. Certifique-se de que os Refresh Tokens na planilha são válidos.")

else:
    st.info("Clique no botão para iniciar a coleta de dados de todas as empresas cadastradas.")
