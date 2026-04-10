# --- SUBSTITUA APENAS O BLOCO DE CONSULTA PELO CÓDIGO ABAIXO ---

if st.button("🚀 Consultar e Gerar Fluxo", type="primary"):
    data_points = []
    lista_alvo = empresas_list if selecao == "TODAS" else [selecao]
    
    with st.expander("🛠️ Log de Depuração Avançado", expanded=True):
        st.markdown('<div class="debug-container">', unsafe_allow_html=True)
        for emp in lista_alvo:
            st.write(f"🔍 Tentando conexão com: **{emp}**")
            
            # 1. Tentar pegar o token
            token = get_new_access_token(emp)
            
            if not token:
                st.error(f"❌ Falha ao renovar Token para {emp}. Verifique se o Client_ID/Secret estão corretos nos Secrets.")
                continue

            # 2. Chamada da API com log de Headers
            url = "https://api.contaazul.com/v1/financeiro/lancamentos"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            params = {
                "data_inicio": d_ini.strftime('%Y-%m-%dT00:00:00Z'), 
                "data_fim": d_fim.strftime('%Y-%m-%dT23:59:59Z')
            }
            
            st.write(f"🛰️ Enviando requisição para API...")
            res = requests.get(url, headers=headers, params=params)
            
            if res.status_code == 200:
                itens = res.json()
                st.success(f"✅ Sucesso! {len(itens)} lançamentos brutos recebidos.")
                # ... resto da lógica de append ...
            elif res.status_code == 401:
                st.error(f"❌ Erro 401 (Não Autorizado)")
                st.write("Dica: O token foi aceito pela autenticação, mas a Conta Azul o rejeitou para esta empresa.")
                st.json(res.json()) # MOSTRA O ERRO REAL AQUI
            else:
                st.error(f"❌ Erro {res.status_code}")
                st.write(res.text)
        st.markdown('</div>', unsafe_allow_html=True)
