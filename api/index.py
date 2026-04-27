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

# Configuração de CORS para permitir que o Frontend acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicialização do Supabase
supabase = create_client(
    os.environ.get("SUPABASE_URL"), 
    os.environ.get("SUPABASE_KEY")
)

def obter_token(empresa_nome):
    """Busca o refresh_token no Supabase e gera um novo access_token da Conta Azul."""
    res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
    if not res.data:
        return None

    refresh_token = res.data["refresh_token"]
    cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
    cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
    auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()

    try:
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
            # Atualiza o refresh_token no banco se a API enviar um novo
            if data.get("refresh_token"):
                supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
            return data["access_token"]
    except Exception as e:
        print(f"Erro ao obter token: {e}")
    return None

def buscar_v2(endpoint, token, params):
    """Busca dados paginados na API v2 da Conta Azul."""
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"tamanho_pagina": 100, "pagina": 1})

    while True:
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params, timeout=10)
        if res.status_code != 200:
            break
        
        dados_json = res.json()
        itens = dados_json.get("itens", [])
        if not itens:
            break
            
        for i in itens:
            # Lógica: Se estivermos buscando PAGOS, usamos o valor total. 
            # Se for EM_ABERTO, usamos apenas o saldo restante.
            valor = i.get("total", 0) if params.get("status") == "PAGO" else (i.get("total", 0) - i.get("pago", 0))
            if valor > 0:
                itens_acum.append({
                    "data": i.get("data_vencimento"),
                    "valor": valor
                })
        
        if len(itens) < 100:
            break
        params["pagina"] += 1
        
    return itens_acum

def buscar_saldo(token):
    """Calcula o saldo somado das contas ITAU, BRADESCO e SICOOB."""
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    bancos_alvo = ["ITAU", "BRADESCO", "SICOOB"]
    
    def normalize(txt):
        return "".join(c for c in unicodedata.normalize('NFD', txt) if unicodedata.category(c) != 'Mn')

    res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
    if res.status_code == 200:
        for conta in res.json().get("itens", []):
            nome = normalize(conta.get("nome", "")).upper()
            if any(b in nome for b in bancos_alvo):
                r = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers, timeout=5)
                if r.status_code == 200:
                    total += r.json().get("saldo_atual", 0)
    return total

@app.get("/api/dados")
def dados(
    empresa: str = Query(...),
    status: str = Query("EM_ABERTO"),
    data_inicio: str = Query(...),
    data_fim: str = Query(...)
):
    token = obter_token(empresa)
    if not token:
        return {"erro": "Falha ao autenticar com a Conta Azul"}

    saldo_bancos = buscar_saldo(token)
    
    # Conversão das datas recebidas do Frontend
    dt_ini = datetime.strptime(data_inicio, "%Y-%m-%d").date()
    dt_fim = datetime.strptime(data_fim, "%Y-%m-%d").date()

    params_base = {
        "data_vencimento_de": dt_ini.isoformat(),
        "data_vencimento_ate": dt_fim.isoformat()
    }
    
    status_list = ["EM_ABERTO", "PAGO"] if status == "TODOS" else [status]
    
    pagar_raw = []
    receber_raw = []
    
    for s in status_list:
        p_params = {**params_base, "status": s}
        pagar_raw.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, p_params))
        receber_raw.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, p_params))

    # Criação do DataFrame para garantir que todos os dias do intervalo apareçam no gráfico
    idx = pd.date_range(dt_ini, dt_fim)
    df = pd.DataFrame(index=idx)
    df.index.name = 'data'
    
    df_p = pd.DataFrame(pagar_raw).groupby("data")["valor"].sum() if pagar_raw else pd.Series(dtype=float)
    df_r = pd.DataFrame(receber_raw).groupby("data")["valor"].sum() if receber_raw else pd.Series(dtype=float)

    df["pagar"] = df_p
    df["receber"] = df_r
    df = df.fillna(0)
    
    # Projeção de saldo acumulado
    df["acumulado"] = saldo_bancos + (df["receber"] - df["pagar"]).cumsum()

    return {
        "datas": df.index.strftime("%Y-%m-%d").tolist(),
        "pagar": df["pagar"].tolist(),
        "receber": df["receber"].tolist(),
        "acumulado": df["acumulado"].tolist(),
        "saldo_bancos": saldo_bancos,
        "total_receber": float(df["receber"].sum()),
        "total_pagar": float(df["pagar"].sum())
    }
