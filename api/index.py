from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import base64
import pandas as pd
import os
import unicodedata
from datetime import datetime
from supabase import create_client

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

# Helper para remover acentos
def remover_acentos(texto):
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

# Função assíncrona para obter token
async def obter_token_async(client, empresa_nome):
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data: return None
        
        cid = os.environ.get("CON_AZUL_CLIENT_ID")
        cs = os.environ.get("CON_AZUL_CLIENT_SECRET")
        auth_b64 = base64.b64encode(f"{cid}:{cs}".encode()).decode()
        
        r = await client.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={"Authorization": f"Basic {auth_b64}"},
            data={"grant_type": "refresh_token", "refresh_token": res.data["refresh_token"]},
            timeout=10
        )
        
        if r.status_code == 200:
            dados = r.json()
            # Atualização do Supabase ainda é síncrona, mas o impacto é baixo aqui
            if dados.get("refresh_token"):
                supabase.table("tokens").update({"refresh_token": dados["refresh_token"]}).eq("empresa", empresa_nome).execute()
            return dados["access_token"]
        return None
    except: return None

# Busca financeira otimizada
async def buscar_v2_async(client, endpoint, token, params):
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    p = {**params, "status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1}
    
    while True:
        res = await client.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p, timeout=15)
        if res.status_code != 200: break
        dados = res.json()
        itens = dados.get('itens', [])
        if not itens: break
        
        for i in itens:
            saldo = i.get('total', 0) - i.get('pago', 0)
            if saldo > 0:
                itens_acumulados.append({"data": i.get("data_vencimento")[:10], "valor": saldo})
        
        if len(itens) < 100: break
        p["pagina"] += 1
    return itens_acumulados

# Busca saldos bancários em paralelo
async def buscar_saldos_async(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    saldo_total = 0
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    try:
        res = await client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
        if res.status_code == 200:
            contas = res.json().get('itens', [])
            # Faz as chamadas de saldo de cada conta em paralelo também
            tarefas = []
            for conta in contas:
                nome = remover_acentos(conta.get('nome', '')).upper()
                if any(banco in nome for banco in bancos_permitidos):
                    tarefas.append(client.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers))
            
            respostas = await asyncio.gather(*tarefas)
            for r in respostas:
                if r.status_code == 200:
                    saldo_total += r.json().get('saldo_atual', 0)
    except: pass
    return saldo_total

# FUNÇÃO PRINCIPAL QUE PROCESSA CADA EMPRESA
async def processar_empresa(client, emp_nome, data_inicio, data_fim):
    token = await obter_token_async(client, emp_nome)
    if not token: return 0, [], []
    
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    
    # Dispara as 3 buscas da empresa simultaneamente
    res_saldo, res_rec, res_desp = await asyncio.gather(
        buscar_saldos_async(client, token),
        buscar_v2_async(client, "/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, params),
        buscar_v2_async(client, "/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, params)
    )
    return res_saldo, res_rec, res_desp

@app.get("/api/dados")
async def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    # 1. Lista as empresas
    if empresa == "todas":
        res_emp = supabase.table("tokens").select("empresa").execute()
        empresas = [r["empresa"] for r in res_emp.data]
    else:
        empresas = [empresa]

    total_saldo_banco = 0
    todas_receitas = []
    todas_despesas = []

    # 2. O MÁGICO: Processa todas as empresas ao mesmo tempo
    async with httpx.AsyncClient() as client:
        tarefas = [processar_empresa(client, e, data_inicio, data_fim) for e in empresas]
        resultados = await asyncio.gather(*tarefas)

    # 3. Consolida os resultados
    for saldo, rec, desp in resultados:
        total_saldo_banco += saldo
        todas_receitas.extend(rec)
        todas_despesas.extend(desp)

    # 4. Pandas para cálculos finais (Mesmo código anterior)
    df_range = pd.date_range(data_inicio, data_fim).strftime('%Y-%m-%d')
    df = pd.DataFrame(index=df_range).assign(receitas=0.0, despesas=0.0)
    
    if todas_receitas:
        df_r = pd.DataFrame(todas_receitas).groupby("data")["valor"].sum()
        df["receitas"] = df.index.map(df_r).fillna(0)
    if todas_despesas:
        df_p = pd.DataFrame(todas_despesas).groupby("data")["valor"].sum()
        df["despesas"] = df.index.map(df_p).fillna(0)

    df["saldo_projetado"] = total_saldo_banco + (df["receitas"] - df["despesas"]).cumsum()
    labels = [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in df.index]

    return {
        "labels": labels,
        "receitas": df["receitas"].tolist(),
        "despesas": df["despesas"].tolist(),
        "saldo": df["saldo_projetado"].tolist(),
        "resumo": {
            "banco": total_saldo_banco,
            "total_rec": float(df["receitas"].sum()),
            "total_desp": float(df["despesas"].sum())
        }
    }
