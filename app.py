# ====================== CALLBACK CONTA AZUL (COLOQUE NO TOPO DO ARQUIVO) ======================
query_params = st.query_params

if 'code' in query_params:
    # Proteção contra loop infinito
    if st.session_state.get('processing_callback', False):
        st.stop()
    
    st.session_state.processing_callback = True
    
    code = query_params.get('code')
    # Se vier como lista, pega o primeiro elemento
    if isinstance(code, list):
        code = code[0]

    st.info("🔄 Recebendo token da Conta Azul...")

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

        # Salva o token no session_state
        st.session_state.pending_token = {
            'access_token': token_data['access_token'],
            'refresh_token': token_data.get('refresh_token'),
            'expires_in': token_data.get('expires_in'),
            'empresa_id': token_data.get('empresa_id')
        }

        # Limpa a URL (remove o ?code=...)
        st.query_params.clear()
        st.success("✅ Token recebido com sucesso!")
        st.rerun()

    except Exception as e:
        st.error(f"❌ Erro ao obter token da Conta Azul: {str(e)}")
        st.session_state.pending_token = None
        st.query_params.clear()
        st.session_state.processing_callback = False
        st.stop()

# ====================== FORMULÁRIO DE NOME DA EMPRESA ======================
if st.session_state.get('pending_token') is not None:
    st.subheader("✅ Conexão com Conta Azul realizada!")
    st.info("Agora informe o nome da empresa para salvar a conexão:")

    with st.form("form_nome_empresa"):
        nome_empresa = st.text_input("Nome da Empresa *", 
                                     value=st.session_state.get('pending_empresa', {}).get("nome", ""),
                                     placeholder="Ex: Empresa XYZ Ltda")

        col1, col2 = st.columns(2)
        with col1:
            cnpj = st.text_input("CNPJ", value=st.session_state.get('pending_empresa', {}).get("cnpj", ""))
        with col2:
            responsavel = st.text_input("Responsável", value=st.session_state.get('pending_empresa', {}).get("responsavel", ""))

        obs = st.text_area("Observações", value=st.session_state.get('pending_empresa', {}).get("observacao", ""))

        if st.form_submit_button("💾 Salvar Empresa"):
            if not nome_empresa.strip():
                st.error("Nome da empresa é obrigatório!")
            else:
                empresa = {
                    "nome": nome_empresa.strip(),
                    "cnpj": cnpj.strip(),
                    "responsavel": responsavel.strip(),
                    "observacao": obs.strip(),
                    "access_token": st.session_state.pending_token["access_token"],
                    "refresh_token": st.session_state.pending_token.get("refresh_token"),
                    "conectado_em": datetime.now().strftime("%d/%m/%Y %H:%M")
                }

                # <<< AQUI VOCÊ SALVA NO GSPREAD >>>
                # salvar_no_google_sheets(empresa)   # sua função atual

                st.success(f"Empresa **{nome_empresa}** salva com sucesso!")
                st.session_state.pending_token = None
                st.session_state.pop('pending_empresa', None)
                st.rerun()

    if st.button("Cancelar"):
        st.session_state.pending_token = None
        st.rerun()
