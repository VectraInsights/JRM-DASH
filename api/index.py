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

# --- CLIENTE SUPABASE ---
supabase = create_client(
    os.environ.get("SUPABASE_URL"), 
    os.environ.get("SUPABASE_KEY")
)

def obter_token(empresa_nome):
    res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
    if not res.data:
        return None

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

def buscar_v2(endpoint, token, params):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1})

    while True:
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params, timeout=10)
        if res.status_code != 200: break
        itens = res.json().get("itens", [])
        if not itens: break
        for i in itens:
            saldo_item = i.get("total", 0) - i.get("pago", 0)
            if saldo_item > 0:
                itens_acum.append({"data": i.get("data_vencimento"), "valor": saldo_item})
        if len(itens) < 100: break
        params["pagina"] += 1
    return itens_acum

def buscar_saldo_real(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    bancos = ["ITAU", "BRADESCO", "SICOOB"]
    normalize = lambda t: "".join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')

    res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
    if res.status_code == 200:
        for conta in res.json().get("itens", []):
            nome = normalize(conta.get("nome", "")).upper()
            if any(b in nome for b in bancos):
                r = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers, timeout=5)
                if r.status_code == 200:
                    total += r.json().get("saldo_atual", 0)
    return total

@app.get("/api/dados")
def dados(
    empresa: str = Query(...),
    data_inicio: str = Query(...),
    data_fim: str = Query(...)
):
    token = obter_token(empresa)
    if not token: return {"erro": "token"}

    saldo_bancos = buscar_saldo_real(token)
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}

    pagar_raw = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, params.copy())
    receber_raw = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, params.copy())

    idx = pd.date_range(data_inicio, data_fim)
    df = pd.DataFrame(index=idx)
    
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
        "total_receber": float(df["receber"].sum()),
        "total_pagar": float(df["pagar"].sum())
    }
