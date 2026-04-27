from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import base64
import pandas as pd
import os
import unicodedata
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

def buscar_v2(endpoint, token, d_ini, d_fim):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    pagina = 1
    
    while True:
        # A API v2 exige o sufixo de fuso horário exato
        params = {
            'pagina': pagina,
            'tamanho_pagina': 100,
            'data_vencimento_de': f"{d_ini}T00:00:00Z",
            'data_vencimento_ate': f"{d_fim}T23:59:59Z",
            'status': 'EM_ABERTO' 
        }
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
            
        dados = res.json()
        itens = dados.get("itens", [])
        if not itens: break
        
        for i in itens:
            valor = i.get("total", 0) - i.get("pago", 0)
            if valor > 0:
                dt = i.get("data_vencimento").split('T')[0]
                itens_acum.append({"data": dt, "valor": float(valor)})
        
        if len(itens) < 100: break
        pagina += 1
    return itens_acum

def buscar_saldo(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
    if res.status_code == 200:
        for conta in res.json().get("itens", []):
            r = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers)
            if r.status_code == 200:
                total += r.json().get("saldo_atual", 0)
    return total

@app.get("/api/dados")
def dados(empresa: str, data_inicio: str, data_fim: str):
    token = obter_token(empresa)
    if not token: return {"erro": "Auth fail"}

    saldo_bancos = buscar_saldo(token)
    pagar = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, data_inicio, data_fim)
    receber = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, data_inicio, data_fim)

    idx = pd.date_range(data_inicio, data_fim)
    df = pd.DataFrame(index=idx)
    
    df_p = pd.DataFrame(pagar).groupby("data")["valor"].sum() if pagar else pd.Series(0, index=df.index)
    df_r = pd.DataFrame(receber).groupby("data")["valor"].sum() if receber else pd.Series(0, index=df.index)

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
