from fastapi import FastAPI, HTTPException
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

# Configuração de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- CONFIGURAÇÃO CLIENTE HTTP ---
# Aumentamos o pool para lidar com múltiplas empresas simultâneas
limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
http_client = httpx.AsyncClient(limits=limits, timeout=20)

@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

# Inicialização Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def remover_acentos(texto):
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

# --- LÓGICA DE AUTENTICAÇÃO ---

async def renovar_e_obter_novo_token(empresa_nome):
    """Renova o access_token usando o refresh_token salvo no Supabase."""
    try:
        print(f"DEBUG: [RENOVAÇÃO] Solicitando novo token para: {empresa_nome}")
        
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data:
            print(f"ERRO: Empresa {empresa_nome} não encontrada no banco.")
            return None

        refresh_token = res.data.get("refresh_token")
        cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
        cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
        auth_b64 = base64.b64encode(f"{cid}:{cs}".encode()).decode()

        url_token = "https://auth.contaazul.com/oauth2/token"
        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        }

        r = await http_client.post(url_token, headers=headers, data=payload)

        if r.status_code == 200:
            dados = r.json()
            novo_access = dados.get("access_token")
            novo_refresh = dados.get("refresh_token")

            supabase.table("tokens").update({
                "access_token": novo_access,
                "refresh_token": novo_refresh,
                "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            
            return novo_access
        else:
            print(f"ERRO: Conta Azul recusou refresh ({r.status_code}) para {empresa_nome}")
            return None

    except Exception as e:
        print(f"DEBUG: [ERRO CRÍTICO RENOVAÇÃO] {e}")
        return None

async def obter_token_atual(empresa_nome):
    """Recupera o token atual. Se falhar, tenta renovar."""
    try:
        res = supabase.table("tokens").select("access_token").eq("empresa", empresa_nome).single().execute()
        if res.data and res.data.get("access_token"):
            return res.data["access_token"]
    except:
        pass
    return await renovar_e_obter_novo_token(empresa_nome)

# --- BUSCAS NA API CONTA AZUL ---

async def buscar_v2_async(endpoint, empresa_nome, params):
    """Busca paginada de lançamentos financeiros (A Pagar/Receber)."""
    token = await obter_token_atual(empresa_nome)
    itens_acumulados = []
    
    p = {
        **params, 
        "status": "EM_ABERTO", 
        "tamanho_pagina": 100, 
        "pagina": 1, 
        "fields": "data_vencimento,total,pago"
    }
    
    tentativas = 0
    while tentativas < 2:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            url = f"https://api-v2.contaazul.com{endpoint}"
            res = await http_client.get(url, headers=headers, params=p)
            
            if res.status_code == 401:
                token = await renovar_e_obter_novo_token(empresa_nome)
                if not token: break
                tentativas += 1
                continue 
            
            if res.status_code != 200: break
            
            dados = res.json()
            itens = dados.get('itens', [])
            if not itens: break
            
            for i in itens:
                valor_aberto = i.get('total', 0) - i.get('pago', 0)
                if valor_aberto > 0:
                    itens_acumulados.append({
                        "data": i.get("data_vencimento")[:10], 
                        "valor": valor_aberto
                    })
            
            if len(itens) < 100: break
            p["pagina"] += 1
            tentativas = 0 
            
        except Exception as e:
            print(f"Erro em {endpoint} para {empresa_nome}: {e}")
            break
            
    return itens_acumulados

async def buscar_saldos_async(token, empresa_nome):
    """Busca o saldo consolidado apenas das contas bancárias permitidas."""
    headers = {"Authorization": f"Bearer {token}"}
    saldo_total = 0
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB", "SICREDI", "SANTANDER", "BANCO DO BRASIL", "NUBANK", "INTER"]
    
    try:
        res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
        
        if res.status_code == 401:
            token = await renovar_e_obter_novo_token(empresa_nome)
            headers = {"Authorization": f"Bearer {token}"}
            res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)

        if res.status_code == 200:
            contas = res.json().get('itens', [])
            tarefas = []
            for conta in contas:
                nome_conta = remover_acentos(conta.get('nome', '')).upper()
                if any(banco in nome_conta for banco in bancos_permitidos):
                    url_saldo = f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual"
                    tarefas.append(http_client.get(url_saldo, headers=headers))
            
            if tarefas:
                respostas = await asyncio.gather(*tarefas)
                for r in respostas:
                    if r.status_code == 200:
                        saldo_total += r.json().get('saldo_atual', 0)
    except Exception as e:
        print(f"Erro ao buscar saldos de {empresa_nome}: {e}")
    return saldo_total

# --- ENDPOINTS API ---

async def processar_empresa(emp_nome, data_inicio, data_fim):
    token = await obter_token_atual(emp_nome)
    if not token: return 0, [], []
    
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dados")
async def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    # Definir quais empresas processar
    if empresa.lower() == "todas":
        res_emp = supabase.table("tokens").select("empresa").execute()
        empresas_nomes = [r["empresa"] for r in res_emp.data]
    else:
        empresas_nomes = [empresa.strip()]

    # Controle de concorrência (Semáforo)
    sem = asyncio.Semaphore(5) 
    
    async def sem_processar(nome):
        async with sem:
            return await processar_empresa(nome, data_inicio, data_fim)

    tarefas = [sem_processar(e) for e in empresas_nomes]
    resultados = await asyncio.gather(*tarefas)

    # Consolidação dos dados
    total_saldo_banco = sum(r[0] for r in resultados)
    todas_receitas = [item for r in resultados for item in r[1]]
    todas_despesas = [item for r in resultados for item in r[2]]

    # Processamento com Pandas para o Gráfico
    df_range = pd.date_range(data_inicio, data_fim).strftime('%Y-%m-%d')
    df = pd.DataFrame(index=df_range).assign(receitas=0.0, despesas=0.0)
    
    if todas_receitas:
        df_r = pd.DataFrame(todas_receitas).groupby("data")["valor"].sum()
        df["receitas"] = df.index.map(df_r).fillna(0)
    
    if todas_despesas:
        df_p = pd.DataFrame(todas_despesas).groupby("data")["valor"].sum()
        df["despesas"] = df.index.map(df_p).fillna(0)

    # Cálculo da projeção de caixa
    df["saldo_projetado"] = total_saldo_banco + (df["receitas"] - df["despesas"]).cumsum()
    
    # Formatação de labels para o frontend (DD/MM)
    labels = [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in df.index]

    return {
        "labels": labels,
        "receitas": df["receitas"].tolist(),
        "despesas": df["despesas"].tolist(),
        "saldo": df["saldo_projetado"].tolist(),
        "resumo": {
            "banco": total_saldo_banco,
            "total_rec": float(df["receitas"].sum()),
            "total_desp": float(df["despesas"].sum()),
            "saldo_final": float(df["saldo_projetado"].iloc[-1]) if not df.empty else total_saldo_banco
        }
    }
