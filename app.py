import requests

# Configurações de Autenticação
ACCESS_TOKEN = "SEU_ACCESS_TOKEN_AQUI"
HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

def obter_todas_as_contas(endpoint, data_inicio, data_fim):
    """
    Função genérica para buscar todas as contas (pagar ou receber) 
    lidando com a paginação da API.
    """
    url = f"https://api.contaazul.com/v1/financeiro/{endpoint}"
    todas_contas = []
    pagina_atual = 1
    
    while True:
        params = {
            "data_vencimento_de": data_inicio,
            "data_vencimento_ate": data_fim,
            "page": pagina_atual,
            "size": 100
        }
        
        try:
            response = requests.get(url, headers=HEADERS, params=params)
            response.raise_for_status()
            dados = response.json()
            
            # Se não houver mais dados, interrompe o loop
            if not dados:
                break
                
            todas_contas.extend(dados)
            
            # Se a quantidade retornada for menor que o 'size', chegamos ao fim
            if len(dados) < 100:
                break
                
            pagina_atual += 1
            
        except requests.exceptions.HTTPError as err:
            print(f"Erro na requisição ao endpoint {endpoint}: {err}")
            break
            
    return todas_contas

# --- Execução Principal ---

# Parâmetros de busca
INICIO = "2026-04-01"
FIM = "2026-04-30"

print(f"--- Iniciando busca de Contas (Cabeçalhos) ---")

# 1. Contas a Receber
lista_receber = obter_todas_as_contas("contas-a-receber", INICIO, FIM)
print(f"Receber: {len(lista_receber)} registros encontrados.")

# 2. Contas a Pagar
lista_pagar = obter_todas_as_contas("contas-a-pagar", INICIO, FIM)
print(f"Pagar: {len(lista_pagar)} registros encontrados.")

# Exemplo de exibição dos dados
if lista_receber:
    print("\nExemplo de Conta a Receber:")
    primeira = lista_receber[0]
    print(f"Cliente: {primeira.get('customer_name')} | Valor Total: {primeira.get('value')}")
