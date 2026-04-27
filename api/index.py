from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
import base64
import pandas as pd
import os
import unicodedata
from datetime import datetime, timedelta
from supabase import create_client

app = FastAPI()

# Configuração de CORS para permitir que o frontend acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicialização do cliente Supabase para gestão de tokens
supabase = create_client(
    os.environ.get("SUPABASE_URL"), 
    os.environ.get("SUPABASE_KEY")
)

def obter_token(empresa_nome):
    """Renova o access_token usando o refresh_token salvo no banco."""
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data:
            return None

        refresh_token = res.data["refresh_token"]
        cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
        cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
        auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()

        response = requests.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("refresh_token"):
                supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
            return data["access_token"]
    except Exception as e:
        print(f"Erro Crítico Token: {e}")
    return None

def buscar_dados_conta_azul(endpoint, token, d_ini, d_fim):
    """Busca registros paginados e filtra apenas o saldo em aberto (Total - Pago)."""
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    pagina = 1

    while True:
        # Formato de data e status conforme documentação oficial CA v2
        params = {
            "pagina": pagina,
            "tamanho_pagina": 100,
            "data_vencimento_de": f"{d_ini}T00:00:00Z",
            "data_vencimento_ate": f"{d_fim}T23:59:59Z",
            "status": "EM_ABERTO"
        }
        
        try:
            res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params, timeout=15)
            if res.status_code != 200:
                break
            
            dados = res.json()
            itens = dados.get("itens", [])
            if not itens:
                break
                
            for item in itens:
                # Lógica de negócio: O que realmente importa é o valor líquido pendente
                valor_liquido = item.get("total", 0) - item.get("pago", 0)
                if valor_liquido > 0:
                    itens_acumulados.append({
                        "data": item.get("data_vencimento").split('T')[0],
                        "valor": valor_liquido
                    })
            
            if len(itens) < 100:
                break
            pagina += 1
        except Exception as e:
            print(f"Erro na paginação {endpoint}: {e}")
            break
            
    return itens_acumulados

def calcular_saldo_bancario(token):
    """Soma o saldo das contas especificadas (Itaú, Bradesco, Sicoob)."""
    headers = {"Authorization": f"Bearer {token}"}
    saldo_total = 0
    bancos_alvo = ["ITAU", "BRADESCO", "SICOOB"]
    
    def remover_acentos(txt):
        return "".join(c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn').upper()

    try:
        res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
        if res.status_code == 200:
            for conta in res.json().get("itens", []):
                nome_conta = remover_acentos(conta.get("nome", ""))
                if any(banco in nome_conta for banco in bancos_alvo):
                    r_saldo = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers, timeout=5)
                    if r_saldo.status_code == 200:
                        saldo_total += r_saldo.json().get("saldo_atual", 0)
    except Exception as e:
        print(f"Erro Saldo Bancário: {e}")
    return saldo_total

@app.get("/api/dados")
def consolidar_dashboard(empresa: str, data_inicio: str, data_fim: str):
    token = obter_token(empresa)
    if not token:
        return {"erro": "Autenticação falhou. Verifique as chaves da API."}

    # 1. Busca Saldo Base
    saldo_inicial = calcular_saldo_bancario(token)
    
    # 2. Busca Movimentações (Pagar e Receber)
    lista_pagar = buscar_dados_conta_azul("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, data_inicio, data_fim)
    lista_receber = buscar_dados_conta_azul("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, data_inicio, data_fim)

    # 3. Processamento de Projeção com Pandas
    datas_range = pd.date_range(data_inicio, data_fim)
    df_mestre = pd.DataFrame(index=datas_range)
    df_mestre.index.name = 'data'
    
    df_p = pd.DataFrame(lista_pagar).groupby("data")["valor"].sum() if lista_pagar else pd.Series(dtype=float)
    df_r = pd.DataFrame(lista_receber).groupby("data")["valor"].sum() if lista_receber else pd.Series(dtype=float)

    df_mestre["pagar"] = df_p
    df_mestre["receber"] = df_r
    df_mestre = df_mestre.fillna(0)
    
    # Cálculo da linha de fluxo acumulado
    df_mestre["fluxo_dia"] = df_mestre["receber"] - df_mestre["pagar"]
    df_mestre["acumulado"] = saldo_inicial + df_mestre["fluxo_dia"].cumsum()

    return {
        "datas": df_mestre.index.strftime("%Y-%m-%d").tolist(),
        "pagar": df_mestre["pagar"].tolist(),
        "receber": df_mestre["receber"].tolist(),
        "acumulado": df_mestre["acumulado"].tolist(),
        "saldo_bancos": saldo_inicial,
        "total_receber": float(df_mestre["receber"].sum()),
        "total_pagar": float(df_mestre["pagar"].sum())
    }
