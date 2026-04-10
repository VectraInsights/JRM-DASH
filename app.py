import streamlit as st
import requests
import base64
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta

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
    </style>
""", unsafe_allow_html=True)

# ====================== CALLBACK CONTA AZUL (ALTERAÇÃO MÍNIMA) ======================
if 'pending_token' not in st.session_state:
    st.session_state.pending_token = None
if 'pending_empresa' not in st.session_state:
    st.session_state.pending_empresa = {}

query_params = st.query_params

if 'code' in query_params and st.session_state.pending_token is None:
    code = query_params.get('code')
    if isinstance(code, list):
        code = code[0]

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
            'empresa_id': token_data.get('empresa_id')
        }

        st.query_params.clear()
        st.rerun()

    except Exception as e:
        st.error(f"Erro ao obter token: {e}")

# ====================== FORMULÁRIO PARA SALVAR O NOME DA EMPRESA ======================
if st.session_state.get('pending_token') is not None:
    st.subheader("✅ Conexão com Conta Azul realizada!")
    st.info("Agora informe o nome da empresa para salvar a conexão.")

    with st.form("form_nome_empresa"):
        nome_empresa = st.text_input("Nome da Empresa *", 
                                     value=st.session_state.pending_empresa.get("nome", ""))

        col1, col2 = st.columns(2)
        with col1:
            cnpj = st.text_input("CNPJ", value=st.session_state.pending_empresa.get("cnpj", ""))
        with col2:
            responsavel = st.text_input("Responsável", value=st.session_state.pending_empresa.get("responsavel", ""))

        observacao = st.text_area("Observações", value=st.session_state.pending_empresa.get("observacao", ""))

        if st.form_submit_button("💾 Salvar Empresa e Token"):
            if not nome_empresa.strip():
                st.error("Nome da empresa é obrigatório!")
            else:
                # Aqui você pode usar exatamente a mesma lógica de salvamento que já tinha no seu código
                empresa_dict = {
                    "nome": nome_empresa.strip(),
                    "cnpj": cnpj.strip(),
                    "responsavel": responsavel.strip(),
                    "observacao": observacao.strip(),
                    "access_token": st.session_state.pending_token["access_token"],
                    "refresh_token": st.session_state.pending_token.get("refresh_token"),
                    "conectado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
                }
                
                # <<< COLE AQUI SUA LÓGICA DE SALVAMENTO NO GSPREAD >>>
                # salvar_no_gspread(empresa_dict)   # sua função original
                
                st.success(f"Empresa **{nome_empresa}** salva com sucesso!")
                st.session_state.pending_token = None
                st.session_state.pending_empresa = {}
                st.rerun()

    if st.button("Cancelar"):
        st.session_state.pending_token = None
        st.rerun()

# ====================== A PARTIR DAQUI É O SEU CÓDIGO ORIGINAL (cole o restante aqui) ======================
