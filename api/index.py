from fastapi import FastAPI, Query
import requests
import base64
import pandas as pd
import os
import json
import unicodedata
from datetime import datetime, timedelta

from supabase import create_client

app = FastAPI()

# -----------------------------
# 🔥 SUPABASE CLIENT
# -----------------------------
supabase = create_client(
    os.environ.get("SUPABASE_URL"),
    os.environ.get("SUPABASE_KEY")  # 🔥 usar SECRET KEY
)

# -----------------------------
# 🔐 TOKEN (SUPABASE)
# -----------------------------
def obter_token(empresa_nome):

    res = supabase.table("tokens") \
        .select("refresh_token") \
        .eq("empresa", empresa_nome) \
        .single() \
        .execute()

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

        # 🔥 atualiza refresh_token automaticamente
        if data.get("refresh_token"):
            supabase.table("tokens") \
                .update({
                    "refresh_token": data["refresh_token"]
                }) \
                .eq("empresa", empresa_nome) \
                .execute()

        return data["access_token"]

    return None


# -----------------------------
# 📡 API CONTA AZUL
# -----------------------------
def buscar_v2(endpoint, token, params):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}

    params.update({
        "status": "EM_ABERTO",
        "tamanho_pagina": 100,
        "pagina": 1
    })

    while True:
        res = requests.get(
            f"https://api-v2.contaazul.com{endpoint}",
            headers=headers,
            params=params,
            timeout=10
        )

        if res.status_code != 200:
            break

        itens = res.json().get("itens", [])
        if not itens:
            break

        for i in itens:
            saldo = i.get("total", 0) - i.get("pago", 0)
            if saldo > 0:
                itens_acum.append({
                    "data": i.get("data_vencimento"),
                    "valor": saldo
                })

        if len(itens) < 100:
            break

        params["pagina"] += 1

    return itens_acum


def buscar_saldo(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0

    bancos = ["ITAU", "BRADESCO", "SICOOB"]

    def normalize(txt):
        return "".join(
            c for c in unicodedata.normalize('NFD', txt)
            if unicodedata.category(c) != 'Mn'
        )

    res = requests.get(
        "https://api-v2.contaazul.com/v1/conta-financeira",
        headers=headers,
        timeout=10
    )

    if res.status_code == 200:
        for conta in res.json().get("itens", []):
            nome = normalize(conta.get("nome", "")).upper()

            if any(b in nome for b in bancos):
                r = requests.get(
                    f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual",
                    headers=headers,
                    timeout=5
                )

                if r.status_code == 200:
                    total += r.json().get("saldo_atual", 0)

    return total


# -----------------------------
# 📋 ENDPOINTS (COM /api)
# -----------------------------
@app.get("/api/clientes")
def clientes():
    res = supabase.table("tokens").select("empresa").execute()
    return [r["empresa"] for r in res.data]


@app.get("/api/dados")
def dados(
    empresa: str = Query(...),
    dias: int = Query(7)
):
    hoje = datetime.now().date()
    data_ini = hoje
    data_fim = hoje + timedelta(days=dias)

    token = obter_token(empresa)
    if not token:
        return {"erro": "token"}

    saldo = buscar_saldo(token)

    params = {
        "data_vencimento_de": data_ini.isoformat(),
        "data_vencimento_ate": data_fim.isoformat()
    }

    pagar = buscar_v2(
        "/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar",
        token,
        params.copy()
    )

    receber = buscar_v2(
        "/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",
        token,
        params.copy()
    )

    df = pd.DataFrame({
        "data": pd.date_range(data_ini, data_fim)
    })

    df["data_str"] = df["data"].dt.strftime("%Y-%m-%d")

    df_p = pd.DataFrame(pagar)
    df_r = pd.DataFrame(receber)

    if not df_p.empty:
        df_p = df_p.groupby("data")["valor"].sum()
    else:
        df_p = pd.Series(dtype=float)

    if not df_r.empty:
        df_r = df_r.groupby("data")["valor"].sum()
    else:
        df_r = pd.Series(dtype=float)

    df["pagar"] = df["data_str"].map(df_p).fillna(0)
    df["receber"] = df["data_str"].map(df_r).fillna(0)

    df["acumulado"] = saldo + (df["receber"] - df["pagar"]).cumsum()

    return {
        "datas": df["data_str"].tolist(),
        "pagar": df["pagar"].tolist(),
        "receber": df["receber"].tolist(),
        "acumulado": df["acumulado"].tolist(),
        "saldo": saldo
    }
