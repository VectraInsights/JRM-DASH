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

# Configuração de CORS para permitir a comunicação com o Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicialização do Cliente Supabase
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def obter_token(empresa_nome):
    """Recupera e renova o token OAuth2 do Conta Azul via Supabase"""
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data:
            return None

        refresh_token = res.data["refresh_token"]
        client_id = os.environ.get("CONTA_AZUL_CLIENT_ID")
        client_secret = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
        
        auth_base64 = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        response = requests.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={
                "Authorization": f"Basic {auth_base64}",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
        )

        if response.status_code == 200:
            data = response.json()
            # Atualiza o refresh token no banco se a API retornar um novo
            if data.get("refresh_token"):
                supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
            return data["access_token"]
        return None
    except Exception:
        return None

def buscar_receitas(token, d_ini, d_fim):
    """Utiliza o endpoint: GET /v1/financeiro/eventos-financeiros/contas-a-receber/buscar"""
    itens_acumulados = []
    pagina = 1
    headers = {"Authorization": f"Bearer {token}"}
    
    while True:
        params = {
            'pagina': pagina,
            'tamanho_pagina': 100,
            'data_vencimento_de': f"{d_ini}T00:00:00Z",
            'data_vencimento_ate': f"{d_fim}T23:59:59Z"
        }
        res = requests.get(
            "https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",
            headers=headers,
            params=params
        )
        if res.status_code != 200:
            break
            
        dados = res.json()
        itens = dados.get("itens", [])
        if not itens:
            break
            
        for i in itens:
            # Filtra apenas o que não foi baixado (receita pendente)
            if i.get("status") != "BAIXADO":
                itens_acumulados.append({
                    "data": i["data_vencimento"][:10],
                    "valor": i["valor"]
                })
        
        if len(itens) < 100:
            break
        pagina += 1
    return itens_acumulados

def buscar_despesas(token, d_ini, d_fim):
    """Utiliza o endpoint: GET /v1/financeiro/contas-a-pagar"""
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        'data_vencimento_de': f"{d_ini}T00:00:00Z",
        'data_vencimento_ate': f"{d_fim}T23:59:59Z"
    }
    res = requests.get(
        "https://api.contaazul.com/v1/financeiro/contas-a-pagar",
        headers=headers,
        params=params
    )
    
    if res.status_code == 200:
        return [
            {"data": i["data_vencimento"][:10], "valor": i["valor"]} 
            for i in res.json() 
            if i.get("status") != "PAGO"
        ]
    return []

@app.get("/api/dados")
def get_dashboard(empresa: str, data_inicio: str, data_fim: str):
    token = obter_token(empresa)
    if not token:
        return {"erro": "Erro de Autenticação"}
    
    # Busca Saldo Bancário Atual
    saldo_total = 0
    res_contas = requests.get("https://api.contaazul.com/v1/conta-financeira", headers={"Authorization": f"Bearer {token}"})
    if res_contas.status_code == 200:
        for conta in res_contas.json():
            r_saldo = requests.get(f"https://api.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual", headers={"Authorization": f"Bearer {token}"})
            if r_saldo.status_code == 200:
                saldo_total += r_saldo.json().get("saldo_atual", 0)

    # Busca Movimentações
    rec = buscar_receitas(token, data_inicio, data_fim)
    desp = buscar_despesas(token, data_inicio, data_fim)

    # Processamento com Pandas para alinhar as datas no gráfico
    datas_range = pd.date_range(data_inicio, data_fim)
    df = pd.DataFrame(index=datas_range).assign(receitas=0.0, despesas=0.0)
    
    if rec:
        df_r = pd.DataFrame(rec).groupby("data")["valor"].sum()
        df.update(df_r.to_frame(name="receitas"))
    if desp:
        df_p = pd.DataFrame(desp).groupby("data")["valor"].sum()
        df.update(df_p.to_frame(name="despesas"))

    df = df.fillna(0)
    df["saldo_projetado"] = saldo_total + (df["receitas"] - df["despesas"]).cumsum()

    return {
        "labels": df.index.strftime("%d/%m").tolist(),
        "receitas": df["receitas"].tolist(),
        "despesas": df["despesas"].tolist(),
        "saldo": df["saldo_projetado"].tolist(),
        "resumo": {
            "banco": saldo_total,
            "total_rec": float(df["receitas"].sum()),
            "total_desp": float(df["despesas"].sum())
        }
    }
