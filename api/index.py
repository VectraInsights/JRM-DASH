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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def obter_token(empresa_nome):
    res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
    if not res.data: return None

    refresh_token = res.data["refresh_token"]
    cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
    cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
    auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()

    response = requests.post(
        "https://auth.contaazul.com/oauth2/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=10
    )

    if response.status_code == 200:
        data = response.json()
        if data.get("refresh_token"):
            supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
        return data["access_token"]
    return None

def buscar_v2(endpoint, token, d_ini, d_fim):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}
    pagina = 1
    
    while True:
        # CORREÇÃO CRÍTICA: Formato de data exigido pela API v2
        params = {
            "data_vencimento_de": f"{d_ini}T00:00:00Z",
            "data_vencimento_ate": f"{d_fim}T23:59:59Z",
            "status": "EM_ABERTO",
            "tamanho_pagina": 100,
            "pagina": pagina
        }

        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params, timeout=10)
        if res.status_code != 200: break
        
        itens = res.json().get("itens", [])
        if not itens: break
        
        for i in itens:
            saldo_item = i.get("total", 0) - i.get("pago", 0)
            if saldo_item > 0:
                # Normaliza a data para YYYY-MM-DD para o Pandas
                dt = i.get("data_vencimento").split('T')[0]
                itens_acum.append({"data": dt, "valor": saldo_item})
        
        if len(itens) < 100: break
        pagina += 1
    return itens_acum

def buscar_saldo(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    bancos = ["ITAU", "BRADESCO", "SICOOB"]
    norm = lambda t: "".join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn').upper()

    res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
    if res.status_code == 200:
        for conta in res.json().get("itens", []):
            nome = norm(conta.get("nome", ""))
            if any(b in nome for b in bancos):
                r = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers, timeout=5)
                if r.status_code == 200:
                    total += r.json().get("saldo_atual", 0)
    return total

@app.get("/api/dados")
def dados(empresa: str, data_inicio: str = None, data_fim: str = None, dias: int = 7):
    # Se não vier data do calendário, usa o padrão de dias
    if not data_inicio or not data_fim:
        hoje = datetime.now().date()
        data_ini_str = hoje.isoformat()
        data_fim_str = (hoje + timedelta(days=dias-1)).isoformat()
    else:
        data_ini_str = data_inicio
        data_fim_str = data_fim

    token = obter_token(empresa)
    if not token: return {"erro": "token"}

    saldo_bancos = buscar_saldo(token)
    pagar_raw = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, data_ini_str, data_fim_str)
    receber_raw = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, data_ini_str, data_fim_str)

    total_receber = sum(i['valor'] for i in receber_raw)
    total_pagar = sum(i['valor'] for i in pagar_raw)

    idx = pd.date_range(data_ini_str, data_fim_str)
    df = pd.DataFrame(index=idx)
    df.index.name = 'data'
    
    df_p = pd.DataFrame(pagar_raw).groupby("data")["valor"].sum() if pagar_raw else pd.Series(dtype=float)
    df_r = pd.DataFrame(receber_raw).groupby("data")["valor"].sum() if receber_raw else pd.Series(dtype=float)

    df["pagar"] = df_p
    df["receber"] = df_r
    df = df.fillna(0)
    df["acumulado"] = saldo_bancos + (df["receber"] - df["pagar"]).cumsum()

    return {
        "datas": df.index.strftime("%Y-%m-%d").tolist(),
        "pagar": df["pagar"].tolist(),
        "receber": df["receber"].tolist(),
        "acumulado": df["acumulado"].tolist(),
        "saldo_bancos": saldo_bancos,
        "total_receber": total_receber,
        "total_pagar": total_pagar
    }
