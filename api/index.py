from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
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
    allow_headers=["*"],
)

supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def obter_token(empresa_nome):
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data: return None

        cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
        cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
        auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()
        
        response = requests.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": res.data["refresh_token"]},
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("refresh_token"):
                supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
            return data["access_token"]
    except:
        pass
    return None

def buscar_ca_api(endpoint, token, d_ini, d_fim):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    pagina = 1
    
    while True:
        # Datas formatadas sem milissegundos para evitar rejeição da API v2
        params = {
            "pagina": pagina,
            "tamanho_pagina": 100,
            "data_vencimento_de": f"{d_ini}T00:00:00Z",
            "data_vencimento_ate": f"{d_fim}T23:59:59Z",
            "status": "EM_ABERTO" 
        }
        
        try:
            res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=params, timeout=15)
            if res.status_code != 200: break
            
            dados = res.json()
            itens = dados.get("itens", [])
            if not itens: break
            
            for i in itens:
                # Captura o valor que ainda falta pagar/receber
                valor_aberto = i.get("total", 0) - i.get("pago", 0)
                if valor_aberto > 0:
                    itens_acum.append({
                        "data": i.get("data_vencimento").split('T')[0], 
                        "valor": valor_aberto
                    })
            
            if len(itens) < 100: break
            pagina += 1
        except:
            break
            
    return itens_acum

def buscar_saldo_bancario(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    bancos_alvo = ["ITAU", "BRADESCO", "SICOOB"]
    norm = lambda t: "".join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn').upper()

    try:
        res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
        if res.status_code == 200:
            for conta in res.json().get("itens", []):
                nome_formatado = norm(conta.get("nome", ""))
                if any(b in nome_formatado for b in bancos_alvo):
                    r = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers=headers, timeout=5)
                    if r.status_code == 200:
                        total += r.json().get("saldo_atual", 0)
    except:
        pass
    return total

@app.get("/api/dados")
def listar_dados(empresa: str, data_inicio: str, data_fim: str):
    token = obter_token(empresa)
    if not token: return {"erro": "Token não encontrado ou expirado"}

    saldo_inicial = buscar_saldo_bancario(token)
    
    # Endpoints de busca específicos da API v2
    pagar = buscar_ca_api("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, data_inicio, data_fim)
    receber = buscar_ca_api("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, data_inicio, data_fim)

    # Consolidação dos dados
    idx = pd.date_range(data_inicio, data_fim)
    df = pd.DataFrame(index=idx)
    
    df_p = pd.DataFrame(pagar).groupby("data")["valor"].sum() if pagar else pd.Series(dtype=float)
    df_r = pd.DataFrame(receber).groupby("data")["valor"].sum() if receber else pd.Series(dtype=float)

    df["pagar"] = df_p
    df["receber"] = df_r
    df = df.fillna(0)
    
    # Cálculo do saldo projetado acumulado
    df["acumulado"] = saldo_inicial + (df["receber"] - df["pagar"]).cumsum()

    return {
        "datas": df.index.strftime("%Y-%m-%d").tolist(),
        "pagar": df["pagar"].tolist(),
        "receber": df["receber"].tolist(),
        "acumulado": df["acumulado"].tolist(),
        "saldo_bancos": saldo_inicial,
        "total_receber": float(df["receber"].sum()),
        "total_pagar": float(df["pagar"].sum())
    }
