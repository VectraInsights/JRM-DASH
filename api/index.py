from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import base64
import pandas as pd
import os
from datetime import datetime
from supabase import create_client

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
        data={"grant_type": "refresh_token", "refresh_token": refresh_token}
    )
    if response.status_code == 200:
        data = response.json()
        if data.get("refresh_token"):
            supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
        return data["access_token"]
    return None

def buscar_receitas(token, d_ini, d_fim):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}
    pagina = 1
    while True:
        params = {
            'pagina': pagina,
            'tamanho_pagina': 100,
            'data_vencimento_de': f"{d_ini}T00:00:00Z",
            'data_vencimento_ate': f"{d_fim}T23:59:59Z",
            'status': 'EM_ABERTO'
        }
        res = requests.get("https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", headers=headers, params=params)
        if res.status_code != 200: break
        dados = res.json()
        itens = dados.get("itens", [])
        if not itens: break
        for i in itens:
            itens_acum.append({"data": i.get("data_vencimento").split('T')[0], "valor": i.get("valor", 0)})
        if len(itens) < 100: break
        pagina += 1
    return itens_acum

def buscar_despesas(token, d_ini, d_fim):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        'data_vencimento_de': f"{d_ini}T00:00:00Z",
        'data_vencimento_ate': f"{d_fim}T23:59:59Z"
    }
    # Conforme sua instrução, este endpoint não usa /buscar no final
    res = requests.get("https://api.contaazul.com/v1/financeiro/contas-a-pagar", headers=headers, params=params)
    if res.status_code == 200:
        for i in res.json():
            # Filtramos apenas as que não foram pagas totalmente
            if i.get("status") != "PAGO":
                itens_acum.append({"data": i.get("data_vencimento").split('T')[0], "valor": i.get("valor", 0)})
    return itens_acum

def buscar_saldo_real(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    res = requests.get("https://api.contaazul.com/v1/conta-financeira", headers=headers)
    if res.status_code == 200:
        for conta in res.json():
            r = requests.get(f"https://api.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers)
            if r.status_code == 200:
                total += r.json().get("saldo_atual", 0)
    return total

@app.get("/api/dados")
def dados(empresa: str, data_inicio: str, data_fim: str):
    token = obter_token(empresa)
    if not token: return {"erro": "Token Inválido"}
    
    saldo_inicial = buscar_saldo_real(token)
    receitas = buscar_receitas(token, data_inicio, data_fim)
    despesas = buscar_despesas(token, data_inicio, data_fim)

    idx = pd.date_range(data_inicio, data_fim)
    df = pd.DataFrame(index=idx)
    df_r = pd.DataFrame(receitas).groupby("data")["valor"].sum() if receitas else pd.Series(0, index=df.index)
    df_p = pd.DataFrame(despesas).groupby("data")["valor"].sum() if despesas else pd.Series(0, index=df.index)
    
    df["receitas"] = df_r
    df["despesas"] = df_p
    df = df.fillna(0)
    df["saldo"] = saldo_inicial + (df["receitas"] - df["despesas"]).cumsum()

    return {
        "datas": df.index.strftime("%Y-%m-%d").tolist(),
        "receitas": df["receitas"].tolist(),
        "despesas": df["despesas"].tolist(),
        "saldo": df["saldo"].tolist(),
        "saldo_banco": saldo_inicial,
        "total_receitas": float(df["receitas"].sum()),
        "total_despesas": float(df["despesas"].sum())
    }
