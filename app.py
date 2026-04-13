import requests
import base64

# Dados do seu prompt
CLIENT_ID = "6s4takgvge1ansrjhsbhhpieor"
CLIENT_SECRET = "1go5jnhckf3l6tatsv7o1t1jf0257fl4a0q6n7to3591g3vjf60l"

def testar_renovacao(refresh_token_da_planilha):
    url = "https://auth.contaazul.com/oauth2/token"
    auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    
    headers = {
        "Authorization": f"Basic {auth_b64}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token_da_planilha
    }
    
    res = requests.post(url, headers=headers, data=data)
    return res.status_code, res.json()

# Chame a função com um token da sua planilha e veja o log
# status, corpo = testar_renovacao("SEU_REFRESH_TOKEN_AQUI")
# print(f"Status: {status}")
# print(corpo)
