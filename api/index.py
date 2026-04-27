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

# Configuração de CORS para permitir que o HTML acesse a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=10
    )

    if response.status_code == 200:
        data = response.json()
        if data.get("refresh_token"):
            supabase.table("tokens").update({"refresh_token": data["refresh_token"]}).eq("empresa", empresa_nome).execute()
        return data["access_token"]
    return None

def buscar_contas_receber(token, d_ini, d_fim):
    """Endpoint: /v1/financeiro/eventos-financeiros/contas-a-receber/buscar"""
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
        res = requests.get(
            "https://api.contaazul.com/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",
            headers=headers,
            params=params
        )
        if res.status_code != 200: break
        
        dados = res.json()
        itens = dados.get("itens", [])
        if not itens: break
        
        for i in itens:
            itens_acum.append({
                "data": i.get("data_vencimento").split('T')[0],
                "valor": i.get("valor", 0)
            })
        
        if len(itens) < 100: break
        pagina += 1
    return itens_acum

def buscar_contas_pagar(token, d_ini, d_fim):
    """Endpoint: /v1/financeiro/contas-a-pagar"""
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
    
    itens_acum = []
    if res.status_code == 200:
        for i in res.json():
            if i.get("status") != "PAGO":
                itens_acum.append({
                    "data": i.get("data_vencimento").split('T')[0],
                    "valor": i.get("valor", 0)
                })
    return itens_acum

def buscar_saldo_bancario(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0
    # Lista de bancos que você monitora
    filtros = ["ITAU", "BRADESCO", "SICOOB"]
    
    res = requests.get("https://api.contaazul.com/v1/conta-financeira", headers=headers)
    if res.status_code == 200:
        contas = res.json()
        for c in contas:
            nome_conta = "".join(ch for ch in unicodedata.normalize('NFD', c['nome']) if unicodedata.category(ch) != 'Mn').upper()
            if any(f in nome_conta for f in filtros):
                r = requests.get(f"https://api.contaazul.com/v1/conta-financeira/{c['id']}/saldo-atual", headers=headers)
                if r.status_code == 200:
                    total += r.json().get("saldo_atual", 0)
    return total

@app.get("/api/dados")
def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    token = obter_token(empresa)
    if not token: return {"erro": "Falha na autenticação"}

    saldo_atual = buscar_saldo_bancario(token)
    receitas_raw = buscar_contas_receber(token, data_inicio, data_fim)
    despesas_raw = buscar_contas_pagar(token, data_inicio, data_fim)

    # Processamento de datas com Pandas para garantir que dias vazios apareçam no gráfico
    datas_range = pd.date_range(start=data_inicio, end=data_fim)
    df = pd.DataFrame(index=datas_range)
    
    df_receitas = pd.DataFrame(receitas_raw).groupby("data")["valor"].sum() if receitas_raw else pd.Series(0, index=df.index)
    df_despesas = pd.DataFrame(despesas_raw).groupby("data")["valor"].sum() if despesas_raw else pd.Series(0, index=df.index)

    df["receitas"] = df_receitas
    df["despesas"] = df_despesas
    df = df.fillna(0)
    
    # Cálculo do saldo acumulado (Saldo Inicial + Receitas - Despesas)
    df["saldo_projetado"] = saldo_atual + (df["receitas"] - df["despesas"]).cumsum()

    return {
        "labels": df.index.strftime("%d/%m").tolist(),
        "receitas": df["receitas"].tolist(),
        "despesas": df["despesas"].tolist(),
        "saldo_projetado": df["saldo_projetado"].tolist(),
        "cards": {
            "saldo_banco": saldo_atual,
            "total_receitas": float(df["receitas"].sum()),
            "total_despesas": float(df["despesas"].sum()),
            "resultado_periodo": float(df["receitas"].sum() - df["despesas"].sum())
        }
    }
