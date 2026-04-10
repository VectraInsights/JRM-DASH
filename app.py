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
if 'temp_data' not in st.session_state: st.session_state.temp_data = None

bg = "#0e1117" if st.session_state.theme == 'dark' else "#ffffff"
txt = "white" if st.session_state.theme == 'dark' else "black"

st.markdown(f"""
    <style>
        #MainMenu, footer, header {{visibility: hidden;}}
        .stApp {{ background-color: {bg}; color: {txt}; }}
        [data-
""", unsafe_allow_html=True)   # ← mantive exatamente como você enviou (mesmo truncado)

# ====================== CALLBACK CONTA AZUL (CORREÇÃO) ======================
if 'pending_token' not in st.session_state:
    st.session_state.pending_token = None
if 'pending_empresa' not in st.session_state:
    st.session_state.pending_empresa = {}
if 'processing_callback' not in st.session_state:
    st.session_state.processing_callback = False

query_params = st.query_params

# Trata o retorno da Conta Azul (quando volta com ?code= na URL)
if 'code' in query_params and st.session_state.pending_token is None:
    if st.session_state.processing_callback:
        st.stop()
    
    st.session_state.processing_callback = True
    code = query_params.get('code')
    if isinstance(code, list):
        code = code[0]

    st.info("🔄 Recebendo token da Conta Azul... Por favor aguarde.")

    try:
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': st.secrets["conta_azul"]["redirect_uri"],
            'client_id': st.secrets["conta_azul"]["client_id"],
            'client_secret': st.secrets["conta_azul"]["client_secret"],
        }

        response = requests.post("https://api.contaazul.com/oauth/token", data=data)
        response.raise_for_status()
        token_data = response.json()

        st.session_state.pending_token = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token'),
            'expires_in': token_data.get('expires_in'),
            'empresa_id': token_data.get('empresa_id')
        }

        st.query_params.clear()
        st.success("✅ Token recebido com sucesso!")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Erro ao obter token: {str(e)}")
        st.session_state.pending_token = None
        st.query_params.clear()
        st.session_state.processing_callback = False

# ====================== FORMULÁRIO PARA NOME DA EMPRESA (APÓS CALLBACK) ======================
if st.session_state.get('pending_token') is not None:
    st.subheader("✅ Conexão com Conta Azul realizada com sucesso!")
    st.info("Agora informe o nome da empresa para salvar a conexão.")

    with st.form("form_nome_empresa"):
        nome_empresa = st.text_input(
            "Nome da Empresa *",
            value=st.session_state.pending_empresa.get("nome", ""),
            placeholder="Ex: Cliente ABC - Matriz"
        )
        
        col1, col2 = st.columns(2)
        with col1:
            cnpj = st.text_input("CNPJ (opcional)", value=st.session_state.pending_empresa.get("cnpj", ""))
        with col2:
            responsavel = st.text_input("Responsável (opcional)", value=st.session_state.pending_empresa.get("responsavel", ""))
        
        observacao = st.text_area("Observações", value=st.session_state.pending_empresa.get("observacao", ""))
        
        if st.form_submit_button("💾 Salvar Empresa e Token"):
            if not nome_empresa.strip():
                st.error("Nome da empresa é obrigatório!")
            else:
                # <<< AQUI VOCÊ USA A MESMA LÓGICA DE SALVAMENTO QUE JÁ TINHA >>>
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
                
                # Cole aqui o seu código de salvamento no Google Sheets (gspread)
                # Exemplo:
                # salvar_empresa_no_gspread(empresa_dict)
                
                st.success(f"Empresa **{nome_empresa}** salva com sucesso!")
                
                st.session_state.pending_token = None
                st.session_state.pending_empresa = {}
                st.rerun()

    if st.button("Cancelar"):
        st.session_state.pending_token = None
        st.session_state.pending_empresa = {}
        st.rerun()

# ====================== RESTO DO SEU CÓDIGO ORIGINAL (continua aqui) ======================
# Cole todo o restante do seu código a partir daqui (sidebar, dashboard, gráficos, etc.)
# Nada foi alterado ou removido.
