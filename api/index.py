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

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# 1. CLIENTE HTTP GLOBAL: Reutiliza conexões TCP (essencial para baixar o tempo no F5)
# Definimos limites para não sobrecarregar as APIs e evitar timeouts
limits = httpx.Limits(max_keepalive_connections=10, max_connections=50)
http_client = httpx.AsyncClient(limits=limits, timeout=10)

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def remover_acentos(texto):
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

async def obter_token_async(empresa_nome):
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data: return None
        
        cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
        cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
        auth_b64 = base64.b64encode(f"{cid}:{cs}".encode()).decode()
        
        r = await http_client.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": res.data["refresh_token"]}
        )
        
        if r.status_code == 200:
            dados = r.json()
            if dados.get("refresh_token"):
                supabase.table("tokens").update({"refresh_token": dados["refresh_token"]}).eq("empresa", empresa_nome).execute()
            return dados["access_token"]
        return None
    except Exception as e:
        print(f"Erro token {empresa_nome}: {e}")
        return None

async def buscar_v2_async(endpoint, token, params):
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    # 2. FILTRO DE CAMPOS: Pede apenas o que o dashboard usa para reduzir o peso do JSON
    p = {
        **params, 
        "status": "EM_ABERTO", 
        "tamanho_pagina": 100, 
        "pagina": 1,
        "fields": "data_vencimento,total,pago" 
    }
    
    while True:
        try:
            res = await http_client.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p)
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
        except: break
    return itens_acumulados

async def buscar_saldos_async(token):
    headers = {"Authorization": f"Bearer {token}"}
    saldo_total = 0
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    try:
        res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
        if res.status_code == 200:
            contas = res.json().get('itens', [])
            tarefas = []
            for conta in contas:
                nome = remover_acentos(conta.get('nome', '')).upper()
                if any(banco in nome for banco in bancos_permitidos):
                    tarefas.append(http_client.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers))
            
            respostas = await asyncio.gather(*tarefas)
            for r in respostas:
                if r.status_code == 200:
                    saldo_total += r.json().get('saldo_atual', 0)
    except: pass
    return saldo_total

async def processar_empresa(emp_nome, data_inicio, data_fim):
    token = await obter_token_async(emp_nome)
    if not token: return 0, [], []
    
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    
    res_saldo, res_rec, res_desp = await asyncio.gather(
        buscar_saldos_async(token),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, params),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, params)
    )
    return res_saldo, res_rec, res_desp

@app.get("/api/empresas")
async def listar_empresas():
    try:
        res = supabase.table("tokens").select("empresa").order("empresa").execute()
        return [{"nome": row["empresa"]} for row in res.data]
    except: return []

@app.get("/api/dados")
async def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    if empresa == "todas":
        res_emp = supabase.table("tokens").select("empresa").execute()
        empresas_nomes = [r["empresa"] for r in res_emp.data]
    else:
        empresas_nomes = [empresa]

    # 3. SEMAPHORE: Evita que o Vercel ou a Conta Azul bloqueiem por excesso de concorrência
    # Se você tiver muitas empresas, isso mantém a estabilidade
    sem = asyncio.Semaphore(10) 
    
    async def sem_processar(nome):
        async with sem:
            return await processar_empresa(nome, data_inicio, data_fim)

    tarefas = [sem_processar(e) for e in empresas_nomes]
    resultados = await asyncio.gather(*tarefas)

    total_saldo_banco = sum(r[0] for r in resultados)
    todas_receitas = [item for r in resultados for item in r[1]]
    todas_despesas = [item for r in resultados for item in r[2]]

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
