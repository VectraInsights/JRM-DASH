from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import base64
import pandas as pd
import os
import unicodedata
from datetime import datetime
from contextlib import asynccontextmanager
from supabase import create_client, Client
from typing import List, Dict, Any
from fastapi.responses import Response
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from io import BytesIO

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

if not all([SUPABASE_URL, SUPABASE_KEY, CLIENT_ID, CLIENT_SECRET]):
    print("⚠️ AVISO: Variáveis de ambiente incompletas no Vercel/Env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- UTILITÁRIOS ---

def remover_acentos(texto: str) -> str:
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

# --- LÓGICA DE AUTENTICAÇÃO COM AVISO NO SUPABASE ---

async def renovar_e_obter_novo_token(empresa_nome: str):
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).execute()
        if not res.data:
            return None

        refresh_token = res.data[0].get("refresh_token")
        auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()

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

            # SUCESSO: Atualiza tokens e limpa qualquer erro anterior
            supabase.table("tokens").update({
                "access_token": novo_access,
                "refresh_token": novo_refresh,
                "status": "ATIVO",
                "mensagem_erro": None,
                "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            
            return novo_access
        else:
            # ERRO DE AUTENTICAÇÃO: Registra o aviso no Supabase
            erro_detalhe = f"Erro {r.status_code} ao renovar: {r.text}"
            supabase.table("tokens").update({
                "status": "ERRO",
                "mensagem_erro": f"Token expirado ou revogado. Reautentique manualmente.",
                "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            return None

    except Exception as e:
        # ERRO DE CONEXÃO/SISTEMA: Registra a falha crítica
        supabase.table("tokens").update({
            "status": "ERRO",
            "mensagem_erro": f"Falha crítica no sistema: {str(e)}",
            "updated_at": datetime.now().isoformat()
        }).eq("empresa", empresa_nome).execute()
        print(f"Erro na renovação de token ({empresa_nome}): {e}")
        return None

async def obter_token_atual(empresa_nome: str):
    try:
        res = supabase.table("tokens").select("access_token, status").eq("empresa", empresa_nome).execute()
        # Se já estiver com erro marcado, tenta renovar uma última vez
        if res.data and res.data[0].get("status") == "ERRO":
             return await renovar_e_obter_novo_token(empresa_nome)
             
        if res.data and res.data[0].get("access_token"):
            return res.data[0]["access_token"]
    except Exception:
        pass
    return await renovar_e_obter_novo_token(empresa_nome)

# --- BUSCAS NA API CONTA AZUL ---

async def buscar_v2_async(endpoint: str, empresa_nome: str, params: dict):
    token = await obter_token_atual(empresa_nome)
    if not token: return []
    
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
                dt_venc = i.get("data_vencimento")[:10] if i.get("data_vencimento") else None
                valor_aberto = i.get('total', 0) - i.get('pago', 0)
                
                if dt_venc and valor_aberto > 0:
                    itens_acumulados.append({
                        "data": dt_venc, 
                        "valor": valor_aberto
                    })
            
            if len(itens) < 100: break
            p["pagina"] += 1
            tentativas = 0 
            
        except Exception as e:
            print(f"Erro de conexão em {endpoint}: {e}")
            break
            
    return itens_acumulados

async def buscar_saldos_async(token: str, empresa_nome: str):
    headers = {"Authorization": f"Bearer {token}"}
    lista_bancos = []
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB", "SICREDI", "SANTANDER", "BANCO DO BRASIL", "NUBANK", "INTER"]
    
    try:
        res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
        
        if res.status_code == 401:
            token = await renovar_e_obter_novo_token(empresa_nome)
            if not token: return []
            headers = {"Authorization": f"Bearer {token}"}
            res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)

        if res.status_code == 200:
            contas = res.json() if isinstance(res.json(), list) else res.json().get('itens', [])
            tarefas = []
            nomes_contas = []

            for conta in contas:
                nome_raw = conta.get('nome', '')
                nome_conta_norm = remover_acentos(nome_raw).upper()
                
                if any(banco in nome_conta_norm for banco in bancos_permitidos):
                    url_saldo = f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual"
                    tarefas.append(http_client.get(url_saldo, headers={"Authorization": f"Bearer {token}"}))
                    nomes_contas.append(nome_raw)
            
            if tarefas:
                respostas = await asyncio.gather(*tarefas, return_exceptions=True)
                for i, r in enumerate(respostas):
                    if isinstance(r, httpx.Response) and r.status_code == 200:
                        saldo = r.json().get('saldo_atual', 0)
                        lista_bancos.append({
                            "nome": nomes_contas[i],
                            "saldo": saldo
                        })
    except Exception as e:
        print(f"Erro ao buscar saldos ({empresa_nome}): {e}")
        
    return lista_bancos

# --- LOGICA DE PROCESSAMENTO ---

async def processar_empresa(emp_nome: str, data_inicio: str, data_fim: str):
    token = await obter_token_atual(emp_nome)
    if not token: return [], [], []
    
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    
    res_bancos, res_rec, res_desp = await asyncio.gather(
        buscar_saldos_async(token, emp_nome),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", emp_nome, params),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", emp_nome, params)
    )
    return res_bancos, res_rec, res_desp

# --- ENDPOINTS ---

@app.get("/api/empresas")
async def listar_empresas():
    try:
        # Agora retorna também o status e a mensagem de erro para o frontend
        res = supabase.table("tokens").select("empresa, status, mensagem_erro").order("empresa").execute()
        return [
            {
                "nome": row["empresa"], 
                "status": row.get("status", "ATIVO"), 
                "erro": row.get("mensagem_erro")
            } for row in res.data
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/dados")
async def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    try:
        if empresa.lower() == "todas":
            res_emp = supabase.table("tokens").select("empresa").execute()
            empresas_nomes = [r["empresa"] for r in res_emp.data]
        else:
            empresas_nomes = [empresa.strip()]

        sem = asyncio.Semaphore(5) 
        
        async def sem_processar(nome):
            async with sem:
                return await processar_empresa(nome, data_inicio, data_fim)

        resultados = await asyncio.gather(*[sem_processar(e) for e in empresas_nomes])

        mapa_bancos = {} 
        for r in resultados:
            for b in r[0]:
                nome_bruto = b["nome"]
                chave_unica = remover_acentos(nome_bruto).upper()
                saldo = b["saldo"]
                
                if chave_unica in mapa_bancos:
                    mapa_bancos[chave_unica]["saldo"] += saldo
                else:
                    mapa_bancos[chave_unica] = {
                        "nome": chave_unica.capitalize(),
                        "saldo": saldo
                    }

        todos_bancos_detalhado = [{"nome": v["nome"], "saldo": round(v["saldo"], 2)} for v in mapa_bancos.values()]
        total_saldo_banco = sum(v["saldo"] for v in mapa_bancos.values())
        
        todas_receitas = [item for r in resultados for item in r[1]]
        todas_despesas = [item for r in resultados for item in r[2]]

        d_inicio = pd.to_datetime(data_inicio)
        d_fim = pd.to_datetime(data_fim)
        datas_range = pd.date_range(d_inicio, d_fim)
        
        df = pd.DataFrame(index=datas_range.strftime('%Y-%m-%d'))
        df["receitas"] = 0.0
        df["despesas"] = 0.0

        if todas_receitas:
            df_r = pd.DataFrame(todas_receitas).groupby("data")["valor"].sum()
            df["receitas"] = df.index.map(df_r).fillna(0)
        
        if todas_despesas:
            df_p = pd.DataFrame(todas_despesas).groupby("data")["valor"].sum()
            df["despesas"] = df.index.map(df_p).fillna(0)

        df["movimentacao_dia"] = df["receitas"] - df["despesas"]
        df["saldo_projetado"] = total_saldo_banco + df["movimentacao_dia"].cumsum()
        
        labels = [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in df.index]

        return {
            "labels": labels,
            "receitas": df["receitas"].tolist(),
            "despesas": df["despesas"].tolist(),
            "saldo": df["saldo_projetado"].tolist(),
            "saldos_por_banco": todos_bancos_detalhado,
            "resumo": {
                "banco": round(float(total_saldo_banco), 2),
                "total_rec": round(float(df["receitas"].sum()), 2),
                "total_desp": round(float(df["despesas"].sum()), 2),
                "saldo_final": round(float(df["saldo_projetado"].iloc[-1]), 2) if not df.empty else total_saldo_banco
            }
        }
    except Exception as e:
        print(f"Erro Crítico: {e}")
        raise HTTPException(status_code=500, detail="Erro ao processar fluxo de caixa.")

async def exportar_pdf(empresa: str, data_inicio: str, data_fim: str):
    try:
        # 1. Busca os dados reais (reaproveitando sua lógica existente)
        dados = await get_dashboard_data(empresa, data_inicio, data_fim)
        
        # 2. Cria o arquivo PDF em memória
        buffer = BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        largura, altura = A4

        # Cabeçalho
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, altura - 50, f"Relatório Financeiro - {empresa}")
        
        p.setFont("Helvetica", 10)
        p.drawString(50, altura - 70, f"Período: {data_inicio} até {data_fim}")
        p.line(50, altura - 80, 550, altura - 80)

        # Resumo Financeiro
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, altura - 110, "Resumo do Período:")
        
        p.setFont("Helvetica", 11)
        resumo = dados["resumo"]
        p.drawString(60, altura - 130, f"Saldo em Banco: R$ {resumo['banco']:,.2f}")
        p.drawString(60, altura - 150, f"Total Receitas: R$ {resumo['total_rec']:,.2f}")
        p.drawString(60, altura - 170, f"Total Despesas: R$ {resumo['total_desp']:,.2f}")
        
        p.setFont("Helvetica-Bold", 11)
        p.drawString(60, altura - 190, f"Saldo Final Projetado: R$ {resumo['saldo_final']:,.2f}")

        # Tabela de Saldos por Banco
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, altura - 230, "Saldos por Instituição:")
        
        y = altura - 250
        p.setFont("Helvetica", 10)
        for banco in dados["saldos_por_banco"]:
            p.drawString(60, y, f"{banco['nome']}: R$ {banco['saldo']:,.2f}")
            y -= 20

        # Rodapé
        p.setFont("Helvetica-Oblique", 8)
        p.drawString(50, 30, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')} - Sistema BPO Financeiro")

        p.showPage()
        p.save()

        # 3. Retorna o arquivo para o navegador
        pdf_out = buffer.getvalue()
        buffer.close()
        
        return Response(
            content=pdf_out,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=relatorio_{empresa}.pdf"}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


