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

# Configuração do Supabase
supabase = create_client(os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY"))

def remover_acentos(texto):
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def obter_token(empresa_nome):
    """Busca o refresh_token no Supabase e renova o acesso na Conta Azul"""
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).single().execute()
        if not res.data: return None
        
        cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
        cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")
        auth_b64 = base64.b64encode(f"{cid}:{cs}".encode()).decode()
        
        r = requests.post(
            "https://auth.contaazul.com/oauth2/token",
            headers={"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token", "refresh_token": res.data["refresh_token"]},
            timeout=10
        )
        
        if r.status_code == 200:
            dados = r.json()
            if dados.get("refresh_token"):
                supabase.table("tokens").update({"refresh_token": dados["refresh_token"]}).eq("empresa", empresa_nome).execute()
            return dados["access_token"]
        return None
    except: return None

def buscar_v2(endpoint, token, params):
    """Busca dados paginados na API v2 filtrando por saldo em aberto"""
    itens_acumulados = []
    headers = {"Authorization": f"Bearer {token}"}
    p = params.copy()
    p.update({"status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1})
    
    while True:
        try:
            res = requests.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p, timeout=15)
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

def buscar_saldos_bancarios(token):
    """Soma saldos apenas das contas ITAU, BRADESCO ou SICOOB"""
    headers = {"Authorization": f"Bearer {token}"}
    saldo_total = 0
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    try:
        res = requests.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers, timeout=10)
        if res.status_code == 200:
            for conta in res.json().get('itens', []):
                nome = remover_acentos(conta.get('nome', '')).upper()
                if any(banco in nome for banco in bancos_permitidos):
                    id_c = conta.get('id')
                    r_s = requests.get(f"https://api-v2.contaazul.com/v1/conta-financeira/{id_c}/saldo-atual", headers=headers, timeout=10)
                    if r_s.status_code == 200:
                        saldo_total += r_s.json().get('saldo_atual', 0)
    except: pass
    return saldo_total

@app.get("/api/empresas")
def listar_empresas():
    """Retorna a lista de empresas para o dropdown do HTML"""
    try:
        res = supabase.table("tokens").select("empresa").execute()
        # Retorna lista de objetos formatada para o JS: [{"nome": "Empresa A"}, ...]
        return [{"nome": row["empresa"]} for row in res.data]
    except:
        return []

@app.get("/api/dados")
def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    # Lista de empresas para processar
    empresas_para_processar = []
    if empresa == "todas":
        res_emp = supabase.table("tokens").select("empresa").execute()
        empresas_para_processar = [r["empresa"] for r in res_emp.data]
    else:
        empresas_para_processar = [empresa]

    total_saldo_banco = 0
    todas_receitas = []
    todas_despesas = []

    # Itera sobre as empresas (se for "todas", soma os resultados)
    for emp_nome in empresas_para_processar:
        token = obter_token(emp_nome)
        if not token: continue
        
        total_saldo_banco += buscar_saldos_bancarios(token)
        
        api_params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
        todas_receitas.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", token, api_params))
        todas_despesas.extend(buscar_v2("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", token, api_params))

    # Processamento com Pandas (Garante o range de datas mesmo se não houver dados)
    df_range = pd.date_range(data_inicio, data_fim).strftime('%Y-%m-%d')
    df = pd.DataFrame(index=df_range).assign(receitas=0.0, despesas=0.0)
    
    if todas_receitas:
        df_r = pd.DataFrame(todas_receitas).groupby("data")["valor"].sum()
        df["receitas"] = df.index.map(df_r).fillna(0)
        
    if todas_despesas:
        df_p = pd.DataFrame(todas_despesas).groupby("data")["valor"].sum()
        df["despesas"] = df.index.map(df_p).fillna(0)

    # Cálculo Acumulado
    df["saldo_projetado"] = total_saldo_banco + (df["receitas"] - df["despesas"]).cumsum()
    labels_formatadas = [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in df.index]

    return {
        "labels": labels_formatadas,
        "receitas": df["receitas"].tolist(),
        "despesas": df["despesas"].tolist(),
        "saldo": df["saldo_projetado"].tolist(),
        "resumo": {
            "banco": total_saldo_banco,
            "total_rec": float(df["receitas"].sum()),
            "total_desp": float(df["despesas"].sum())
        }
    }
