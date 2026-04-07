def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    # Limpeza rigorosa do token (remove espaços e quebras de linha invisíveis)
    refresh_token_clean = str(refresh_token_raw).strip()
    
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_clean,
        "scope": "openid profile aws.cognito.signin.user.admin"
    }
    
    try:
        # Usando autenticação Basic com Client ID e Secret
        response = requests.post(
            url, 
            auth=(CLIENT_ID, CLIENT_SECRET), 
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")
            # Atualiza na planilha se o Conta Azul enviar um novo Refresh Token (Rotatividade)
            if novo_refresh and novo_refresh != refresh_token_clean:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            
            return dados.get("access_token")
        else:
            st.error(f"Erro ao renovar Token para {empresa}: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        st.error(f"Falha na comunicação de Auth: {e}")
        return None

def buscar_financeiro_v1_novo(token, tipo):
    # Endpoint oficial da documentação OIDC
    url = f"https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-{tipo}/buscar"
    
    # Headers precisam ser exatamente assim
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    params = {
        "pagina": 1,
        "tamanho_pagina": 1000,
        "data_vencimento_de": "2025-01-01T00:00:00Z",
        "data_vencimento_ate": "2027-12-31T23:59:59Z"
    }
    
    try:
        r = requests.get(url, headers=headers, params=params)
        if r.status_code == 200:
            data = r.json()
            # A API V1 pode retornar 'items' ou 'itens'
            return data.get("items", data.get("itens", []))
        elif r.status_code == 401:
            st.warning(f"⚠️ Token Recusado pela API de {tipo.upper()}. Verifique as permissões do App no portal.")
            return []
        else:
            st.error(f"Erro {tipo}: {r.status_code}")
            return []
    except:
        return []
