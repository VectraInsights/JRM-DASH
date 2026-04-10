import streamlit as st
import requests
from urllib.parse import urlencode
import uuid

# ====================== CONFIGURAÇÕES CONTA AZUL ======================
CLIENT_ID = st.secrets["conta_azul"]["client_id"]
CLIENT_SECRET = st.secrets["conta_azul"]["client_secret"]
REDIRECT_URI = st.secrets["conta_azul"]["redirect_uri"]   # ex: https://seu-app.streamlit.app/callback

AUTH_URL = "https://api.contaazul.com/oauth/authorize"
TOKEN_URL = "https://api.contaazul.com/oauth/token"

# ====================== SESSION STATE ======================
if 'pending_token' not in st.session_state:
    st.session_state.pending_token = None
if 'pending_empresa' not in st.session_state:
    st.session_state.pending_empresa = {}

# ====================== DETECTAR CALLBACK ======================
query_params = st.query_params

if 'code' in query_params and st.session_state.pending_token is None:
    code = query_params['code']
    
    # Troca code por token
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    }
    
    try:
        response = requests.post(TOKEN_URL, data=data)
        response.raise_for_status()
        token_data = response.json()
        
        st.session_state.pending_token = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token'),
            'expires_in': token_data.get('expires_in'),
            'empresa_id': token_data.get('empresa_id')  # se a Conta Azul retornar
        }
        
        # Limpa os query params para evitar loop
        st.query_params.clear()
        st.rerun()
        
    except Exception as e:
        st.error(f"Erro ao obter token: {e}")
        st.query_params.clear()

# ====================== FORMULÁRIO PARA NOME DA EMPRESA (APÓS CALLBACK) ======================
if st.session_state.pending_token is not None:
    st.subheader("✅ Conexão com Conta Azul realizada com sucesso!")
    st.info("Agora dê um nome identificador para esta empresa no seu dashboard.")

    with st.form("form_nome_empresa"):
        nome_empresa = st.text_input(
            "Nome da Empresa *", 
            value=st.session_state.pending_empresa.get("nome", ""),
            placeholder="Ex: Cliente ABC - Matriz",
            help="Esse é o nome que aparecerá no seu dashboard"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            cnpj = st.text_input("CNPJ (opcional)", value=st.session_state.pending_empresa.get("cnpj", ""))
        with col2:
            responsavel = st.text_input("Responsável (opcional)", value=st.session_state.pending_empresa.get("responsavel", ""))
        
        observacao = st.text_area("Observações", value=st.session_state.pending_empresa.get("observacao", ""))
        
        salvar = st.form_submit_button("💾 Salvar Empresa e Token")
        
        if salvar:
            if not nome_empresa.strip():
                st.error("O nome da empresa é obrigatório!")
            else:
                # Salva tudo junto (token + dados da empresa)
                empresa_dict = {
                    "nome": nome_empresa.strip(),
                    "cnpj": cnpj.strip(),
                    "responsavel": responsavel.strip(),
                    "observacao": observacao.strip(),
                    "access_token": st.session_state.pending_token["access_token"],
                    "refresh_token": st.session_state.pending_token.get("refresh_token"),
                    "conectado_em": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "conta_azul_id": st.session_state.pending_token.get("empresa_id")
                }
                
                # Aqui você salva no Google Sheets (gspread) ou no seu banco
                # Exemplo:
                # salvar_no_google_sheets(empresa_dict)
                
                st.success(f"Empresa **{nome_empresa}** salva com sucesso!")
                
                # Limpa o pending
                st.session_state.pending_token = None
                st.session_state.pending_empresa = {}
                st.rerun()

    if st.button("Cancelar conexão"):
        st.session_state.pending_token = None
        st.session_state.pending_empresa = {}
        st.rerun()
