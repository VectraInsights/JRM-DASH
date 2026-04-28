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

# CLIENTE HTTP GLOBAL
limits = httpx.Limits(max_keepalive_connections=10, max_connections=50)
http_client = httpx.AsyncClient(limits=limits, timeout=15) # Aumentado levemente para evitar timeouts em renovações

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def remover_acentos(texto):
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

# --- LOGICA DE TOKEN ---

async def renovar_e_obter_novo_token(empresa_nome):
    """
    Força a renovação do token na Conta Azul e garante a atualização 
    dos dois tokens (Access e Refresh) no Supabase.
    """
    try:
        print(f"DEBUG: [RENOVAÇÃO] Iniciando processo para: {empresa_nome}")
        
        # 1. Busca as credenciais atuais para ter o Refresh Token inicial
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data or not res.data.get("refresh_token"):
            print(f"ERRO: Nenhum refresh_token encontrado para {empresa_nome} no Supabase.")
            return None

        # 2. Prepara a autenticação (Client ID e Secret)
        cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
        cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
        auth_b64 = base64.b64encode(f"{cid}:{cs}".encode()).decode()

        # 3. Faz a chamada POST para a Conta Azul
        url_token = "https://auth.contaazul.com/oauth2/token"
        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": res.data["refresh_token"]
        }

        r = await http_client.post(url_token, headers=headers, data=payload)

        # 4. Processa o sucesso
        if r.status_code == 200:
            dados = r.json()
            novo_access = dados.get("access_token")
            novo_refresh = dados.get("refresh_token")

            # ATUALIZAÇÃO CRÍTICA: Salva ambos os tokens no banco
            supabase.table("tokens").update({
                "access_token": novo_access,
                "refresh_token": novo_refresh,
                "updated_at": "now()" # Garante que o timestamp de atualização mude
            }).eq("empresa", empresa_nome).execute()
            
            print(f"DEBUG: [SUCESSO] Tokens atualizados para {empresa_nome}.")
            return novo_access
        
        else:
            print(f"DEBUG: [FALHA] Conta Azul recusou o refresh ({r.status_code}): {r.text}")
            return None

    except Exception as e:
        print(f"DEBUG: [ERRO CRÍTICO] Falha na função de renovação: {e}")
        return None

async def obter_token_atual(empresa_nome):
    """Tenta pegar o access_token já salvo antes de tentar renovar"""
    res = supabase.table("tokens").select("access_token").eq("empresa", empresa_nome).single().execute()
    if res.data and res.data.get("access_token"):
        return res.data["access_token"]
    return await renovar_e_obter_novo_token(empresa_nome)

# --- REQUISIÇÕES COM RETRY AUTOMÁTICO ---

async def buscar_v2_async(endpoint, empresa_nome, params):
    token = await obter_token_atual(empresa_nome)
    itens_acumulados = []
    
    p = {**params, "status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1, "fields": "data_vencimento,total,pago"}
    
    tentativas = 0
    while tentativas < 2:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            res = await http_client.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p)
            
            if res.status_code == 401: # TOKEN EXPIRADO
                print(f"DEBUG: Token expirado em {endpoint} para {empresa_nome}. Tentando renovar...")
                token = await renovar_e_obter_novo_token(empresa_nome)
                if not token: break
                tentativas += 1
                continue # Tenta novamente com o novo token
            
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
            tentativas = 0 # Reseta tentativas para a próxima página
            
        except Exception as e:
            print(f"Erro na busca v2: {e}")
            break
    return itens_acumulados

async def buscar_saldos_async(token, empresa_nome):
    headers = {"Authorization": f"Bearer {token}"}
    saldo_total = 0
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    
    try:
        res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
        
        # Se der 401 aqui, renovamos. Como esta função é chamada via gather, 
        # o ideal é que obter_token_atual já tenha resolvido, mas tratamos por segurança:
        if res.status_code == 401:
            novo_token = await renovar_e_obter_novo_token(empresa_nome)
            headers = {"Authorization": f"Bearer {novo_token}"}
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
    except Exception as e:
        print(f"Erro saldos {empresa_nome}: {e}")
    return saldo_total

# --- PROCESSAMENTO PRINCIPAL ---

async def processar_empresa(emp_nome, data_inicio, data_fim):
    token = await obter_token_atual(emp_nome)
    if not token: return 0, [], []
    
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    
    # Passamos o nome da empresa para as funções lidarem com o refresh se necessário
    res_saldo, res_rec, res_desp = await asyncio.gather(
        buscar_saldos_async(token, emp_nome),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", emp_nome, params),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", emp_nome, params)
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
