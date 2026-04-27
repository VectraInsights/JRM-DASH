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

# Cliente Supabase para gerenciar os Refresh Tokens
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def remover_acentos(texto):
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def obter_token(empresa_nome):
    """Busca o refresh_token no Supabase e renova na Conta Azul"""
    res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
    if not res.data: return None
    
    cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
    cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
    auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()
    
    response = requests.post(
        "https://auth.contaazul.com/oauth2/token",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": res.data["refresh_token"]}
    )
    
    if response.status_code == 200:
        data = response.json()
        if data.get("refresh_token"):
            supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
        return data["access_token"]
    return None

def buscar_v2(endpoint, token, params):
    """Réplica exata da lógica buscar_v2 do seu Streamlit"""
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    params.update({"status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1})
    
    while True:
        # Nota: Usando api-v2 conforme seu código
        res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params)
        if res.status_code != 200: break
        
        itens = res.json().get('itens', [])
        if not itens: break
        
        for i in itens:
            saldo = i.get('total', 0) - i.get('pago', 0)
            if saldo > 0:
                itens_acumulados.append({
                    "data": i.get("data_vencimento")[:10], 
                    "valor": saldo
                })
        
        if len(itens) < 100: break
        params["pagina"] += 1
    return itens_acumulados

def buscar_saldos(token):
    """Filtra apenas ITAU, BRADESCO e SICOOB conforme seu script"""
    headers = {"Authorization": f"Bearer {token}"}
    saldo_total = 0
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    
    try:
        res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
        if res.status_code == 200:
            for conta in res.json().get('itens', []):
                nome_limpo = remover_acentos(conta.get('nome', '')).upper()
                if any(b in nome_limpo for b in bancos_permitidos):
                    id_c = conta.get('id')
                    r_s = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{id_c}/saldo-atual", headers=headers)
                    if r_s.status_code == 200:
                        saldo_total += r_s.json().get('saldo_atual', 0)
    except: pass
    return saldo_total

@app.get("/api/dados")
def dashboard(empresa: str, data_inicio: str, data_fim: str):
    token = obter_token(empresa)
    if not token: return {"erro": "Token Inválido"}
    
    saldo_inicial = buscar_saldos(token)
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    
    # Busca Receitas e Despesas
    rec = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, params.copy())
    desp = buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, params.copy())

    # Consolidação de dados
    df_range = pd.date_range(data_inicio, data_fim)
    df = pd.DataFrame(index=df_range).assign(receitas=0.0, despesas=0.0)
    
    if rec:
        df_r = pd.DataFrame(rec).groupby("data")["valor"].sum()
        df["receitas"] = df_r
    if desp:
        df_p = pd.DataFrame(desp).groupby("data")["valor"].sum()
        df["despesas"] = df_p

    df = df.fillna(0)
    df["saldo_proj"] = saldo_inicial + (df["receitas"] - df["despesas"]).cumsum()

    return {
        "labels": df.index.strftime("%d/%m").tolist(),
        "receitas": df["receitas"].tolist(),
        "despesas": df["despesas"].tolist(),
        "saldo": df["saldo_proj"].tolist(),
        "totais": {
            "banco": saldo_inicial,
            "rec": float(df["receitas"].sum()),
            "desp": float(df["despesas"].sum())
        }
    }
