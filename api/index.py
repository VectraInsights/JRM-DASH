from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import base64
import pandas as pd
import os
import unicodedata
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from contextlib import asynccontextmanager
from supabase import create_client, Client
from typing import List, Dict, Any

# --- VARIÁVEIS GLOBAIS ---
http_client: httpx.AsyncClient = None

# --- GERENCIAMENTO DE CICLO DE VIDA ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    http_client = httpx.AsyncClient(limits=limits, timeout=30.0)
    yield
    await http_client.aclose()

app = FastAPI(lifespan=lifespan)

# --- CONFIGURAÇÃO DE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- CONFIGURAÇÕES DE AMBIENTE ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
CLIENT_ID = os.environ.get("CONTA_AZUL_CLIENT_ID")
CLIENT_SECRET = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- UTILITÁRIOS ---

def remover_acentos(texto: str) -> str:
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def enviar_alerta_email(empresa_nome: str, mensagem_erro: str):
    if not all([EMAIL_USER, EMAIL_PASS, EMAIL_RECEIVER]):
        return

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = f"⚠️ FALHA DE TOKEN: {empresa_nome}"

    corpo = f"""
    Falha na renovação do token da Conta Azul.
    Empresa: {empresa_nome}
    Erro: {mensagem_erro}
    Ação: Reautentique manualmente via URL de Callback.
    """
    msg.attach(MIMEText(corpo, 'plain'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
    except Exception as e:
        print(f"Erro ao enviar email: {e}")

# --- ROTA DE CALLBACK (NOVA) ---

@app.get("/api/callback")
async def callback(code: str, state: str = None):
    """Recebe o código da Conta Azul e salva o primeiro token no Supabase."""
    if not code:
        raise HTTPException(status_code=400, detail="Código não fornecido.")

    auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    payload = {
        "grant_type": "authorization_code",
        "redirect_uri": "https://jrm-dashboard.vercel.app/api/callback",
        "code": code
    }
    
    headers = {"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"}

    async with httpx.AsyncClient() as client:
        r = await client.post("https://auth.contaazul.com/oauth2/token", headers=headers, data=payload)
        if r.status_code != 200:
            return {"status": "erro", "detalhe": r.text}
        
        dados = r.json()
        access = dados.get("access_token")
        refresh = dados.get("refresh_token")

        # Busca nome da empresa para identificar no banco
        info = await client.get("https://api-v2.contaazul.com/v1/info", headers={"Authorization": f"Bearer {access}"})
        nome_empresa = info.json().get("name", "Nova Empresa").upper() if info.status_code == 200 else "EMPRESA_DESCONHECIDA"

        supabase.table("tokens").upsert({
            "empresa": nome_empresa,
            "access_token": access,
            "refresh_token": refresh,
            "status": "ATIVO",
            "updated_at": datetime.now().isoformat()
        }).execute()

    return {"status": "sucesso", "mensagem": f"Empresa {nome_empresa} conectada!"}

# --- LÓGICA DE RENOVAÇÃO ---

async def renovar_e_obter_novo_token(empresa_nome: str):
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).execute()
        if not res.data: return None

        refresh_token = res.data[0].get("refresh_token")
        auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        headers = {"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"}

        r = await http_client.post("https://auth.contaazul.com/oauth2/token", headers=headers, data=payload)

        if r.status_code == 200:
            dados = r.json()
            novo_access = dados.get("access_token")
            novo_refresh = dados.get("refresh_token")

            supabase.table("tokens").update({
                "access_token": novo_access,
                "refresh_token": novo_refresh,
                "status": "ATIVO",
                "mensagem_erro": None,
                "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            return novo_access
        else:
            supabase.table("tokens").update({
                "status": "ERRO",
                "mensagem_erro": "Token expirado. Reautentique.",
                "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            enviar_alerta_email(empresa_nome, r.text)
            return None
    except Exception as e:
        print(f"Erro crítico renovação: {e}")
        return None

async def obter_token_atual(empresa_nome: str):
    res = supabase.table("tokens").select("access_token, status").eq("empresa", empresa_nome).execute()
    if res.data and res.data[0].get("status") == "ATIVO":
        return res.data[0]["access_token"]
    return await renovar_e_obter_novo_token(empresa_nome)

# --- BUSCAS E PROCESSAMENTO ---

async def buscar_v2_async(endpoint: str, empresa_nome: str, params: dict):
    token = await obter_token_atual(empresa_nome)
    if not token: return []
    
    itens_acumulados = []
    p = {**params, "status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1, "fields": "data_vencimento,total,pago"}
    
    while True:
        headers = {"Authorization": f"Bearer {token}"}
        res = await http_client.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p)
        
        if res.status_code == 401:
            token = await renovar_e_obter_novo_token(empresa_nome)
            if not token: break
            continue
        
        if res.status_code != 200: break
        
        dados = res.json()
        itens = dados.get('itens', [])
        if not itens: break
        
        for i in itens:
            dt_venc = i.get("data_vencimento")[:10] if i.get("data_vencimento") else None
            valor_aberto = i.get('total', 0) - i.get('pago', 0)
            if dt_venc and valor_aberto > 0:
                itens_acumulados.append({"data": dt_venc, "valor": valor_aberto})
        
        if len(itens) < 100: break
        p["pagina"] += 1
            
    return itens_acumulados

async def buscar_saldos_async(token: str, empresa_nome: str):
    headers = {"Authorization": f"Bearer {token}"}
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB", "SICREDI", "SANTANDER", "BANCO DO BRASIL", "NUBANK", "INTER"]
    lista_bancos = []
    
    res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
    if res.status_code == 200:
        contas = res.json() if isinstance(res.json(), list) else res.json().get('itens', [])
        for conta in contas:
            nome_raw = conta.get('nome', '')
            if any(b in remover_acentos(nome_raw).upper() for b in bancos_permitidos):
                r_s = await http_client.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers)
                if r_s.status_code == 200:
                    lista_bancos.append({"nome": nome_raw, "saldo": r_s.json().get('saldo_atual', 0)})
    return lista_bancos

# --- ENDPOINTS ---

@app.get("/api/empresas")
async def listar_empresas():
    res = supabase.table("tokens").select("empresa, status, mensagem_erro").order("empresa").execute()
    return [{"nome": row["empresa"], "status": row.get("status"), "erro": row.get("mensagem_erro")} for row in res.data]

@app.get("/api/dados")
async def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    try:
        if empresa.lower() == "todas":
            res_emp = supabase.table("tokens").select("empresa").eq("status", "ATIVO").execute()
            empresas_nomes = [r["empresa"] for r in res_emp.data]
        else:
            empresas_nomes = [empresa.strip()]

        async def processar(nome):
            token = await obter_token_atual(nome)
            if not token: return [], [], []
            p = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
            return await asyncio.gather(
                buscar_saldos_async(token, nome),
                buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", nome, p),
                buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", nome, p)
            )

        resultados = await asyncio.gather(*[processar(e) for e in empresas_nomes])

        # Consolidação (Pandas)
        mapa_bancos = {}
        for r in resultados:
            for b in r[0]:
                chave = remover_acentos(b["nome"]).upper()
                mapa_bancos[chave] = mapa_bancos.get(chave, 0) + b["saldo"]

        total_banco = sum(mapa_bancos.values())
        rec = [item for r in resultados for item in r[1]]
        desp = [item for r in resultados for item in r[2]]

        df = pd.DataFrame(index=pd.date_range(data_inicio, data_fim).strftime('%Y-%m-%d'))
        df["receitas"] = pd.DataFrame(rec).groupby("data")["valor"].sum() if rec else 0
        df["despesas"] = pd.DataFrame(desp).groupby("data")["valor"].sum() if desp else 0
        df = df.fillna(0)
        
        df["saldo_projetado"] = total_banco + (df["receitas"] - df["despesas"]).cumsum()

        return {
            "labels": [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in df.index],
            "receitas": df["receitas"].tolist(),
            "despesas": df["despesas"].tolist(),
            "saldo": df["saldo_projetado"].tolist(),
            "saldos_por_banco": [{"nome": k.capitalize(), "saldo": round(v, 2)} for k, v in mapa_bancos.items()],
            "resumo": {
                "banco": round(total_banco, 2),
                "total_rec": round(df["receitas"].sum(), 2),
                "total_desp": round(df["despesas"].sum(), 2),
                "saldo_final": round(df["saldo_projetado"].iloc[-1], 2)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
