from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import httpx
import asyncio
import base64
import pandas as pd
import os
import unicodedata
import io
from datetime import datetime
from contextlib import asynccontextmanager
from supabase import create_client, Client
from typing import List, Dict, Any, Optional
from fastapi.responses import Response
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from io import BytesIO
from pydantic import BaseModel

# --- MODELOS DE DADOS ---
class ExportarRequest(BaseModel):
    empresa: str
    data_inicio: str
    data_fim: str
    chart_image: Optional[str] = None

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

app = FastAPI(lifespan=lifespan, title="API JRM Gestão - BPO Financeiro")

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

if not all([SUPABASE_URL, SUPABASE_KEY]):
    raise RuntimeError("Erro: SUPABASE_URL ou SUPABASE_KEY não configurados.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- UTILITÁRIOS ---

def remover_acentos(texto: str) -> str:
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def identificar_banco_principal(nome_raw: str) -> str:
    """Padroniza nomes de bancos para agrupamento (Itaú, Itau, ITAU -> ITAÚ)."""
    nome = remover_acentos(nome_raw).upper()
    if "ITAU" in nome: return "ITAÚ"
    if "BRADESCO" in nome: return "BRADESCO"
    if "SICOOB" in nome: return "SICOOB"
    return nome_raw.upper()

# --- LÓGICA DE AUTENTICAÇÃO ---

async def renovar_e_obter_novo_token(empresa_nome: str):
    try:
        res = supabase.table("tokens").select("refresh_token").eq("empresa", empresa_nome).execute()
        if not res.data: return None
        refresh_token = res.data[0].get("refresh_token")
        auth_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        url_token = "https://auth.contaazul.com/oauth2/token"
        headers = {"Authorization": f"Basic {auth_b64}", "Content-Type": "application/x-www-form-urlencoded"}
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        r = await http_client.post(url_token, headers=headers, data=payload)
        if r.status_code == 200:
            dados = r.json()
            novo_access, novo_refresh = dados.get("access_token"), dados.get("refresh_token")
            supabase.table("tokens").update({
                "access_token": novo_access, "refresh_token": novo_refresh,
                "status": "ATIVO", "mensagem_erro": None, "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            return novo_access
        else:
            supabase.table("tokens").update({
                "status": "ERRO", "mensagem_erro": f"Falha na renovação (HTTP {r.status_code}).",
                "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            return None
    except Exception: return None

async def obter_token_atual(empresa_nome: str):
    try:
        res = supabase.table("tokens").select("access_token, status").eq("empresa", empresa_nome).execute()
        if res.data and res.data[0].get("status") == "ERRO": return await renovar_e_obter_novo_token(empresa_nome)
        if res.data and res.data[0].get("access_token"): return res.data[0]["access_token"]
    except Exception: pass
    return await renovar_e_obter_novo_token(empresa_nome)

# --- BUSCAS NA API ---

async def buscar_v2_async(endpoint: str, empresa_nome: str, params: dict):
    token = await obter_token_atual(empresa_nome)
    if not token: return []
    itens_acumulados, p = [], {**params, "status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1}
    tentativas = 0
    while tentativas < 2:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            res = await http_client.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p)
            if res.status_code == 401:
                token = await renovar_e_obter_novo_token(empresa_nome)
                if not token: break
                tentativas += 1; continue 
            if res.status_code != 200: break
            itens = res.json().get('itens', [])
            if not itens: break
            for i in itens:
                dt_venc = i.get("data_vencimento")[:10] if i.get("data_vencimento") else None
                valor_aberto = i.get('total', 0) - i.get('pago', 0)
                if dt_venc and valor_aberto > 0: itens_acumulados.append({"data": dt_venc, "valor": valor_aberto})
            if len(itens) < 100: break
            p["pagina"] += 1
        except Exception: break
    return itens_acumulados

async def buscar_saldos_async(token: str, empresa_nome: str):
    headers = {"Authorization": f"Bearer {token}"}
    lista_bancos = []
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    try:
        res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
        if res.status_code == 200:
            contas = res.json() if isinstance(res.json(), list) else res.json().get('itens', [])
            tarefas, nomes_contas = [], []
            for conta in contas:
                nome_raw = conta.get('nome', '')
                nome_limpo = remover_acentos(nome_raw).upper()
                # Filtra bancos permitidos e remove contas "AP." ou "Aplicação"
                if any(b in nome_limpo for b in bancos_permitidos) and " AP." not in nome_limpo and "APLICACAO" not in nome_limpo:
                    url_saldo = f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual"
                    tarefas.append(http_client.get(url_saldo, headers={"Authorization": f"Bearer {token}"}))
                    nomes_contas.append(nome_raw)
            if tarefas:
                respostas = await asyncio.gather(*tarefas, return_exceptions=True)
                for i, r in enumerate(respostas):
                    if isinstance(r, httpx.Response) and r.status_code == 200:
                        lista_bancos.append({"nome": nomes_contas[i], "saldo": round(r.json().get('saldo_atual', 0), 2)})
    except Exception: pass
    return lista_bancos

# --- PROCESSAMENTO CENTRAL ---

async def processar_empresa(emp_nome: str, data_inicio: str, data_fim: str):
    token = await obter_token_atual(emp_nome)
    if not token: return [], [], []
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    return await asyncio.gather(
        buscar_saldos_async(token, emp_nome),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", emp_nome, params),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", emp_nome, params)
    )

async def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    try:
        empresas_nomes = [empresa.strip()] if empresa.lower() != "todas" else [r["empresa"] for r in (supabase.table("tokens").select("empresa").execute()).data]
        resultados = await asyncio.gather(*[processar_empresa(e, data_inicio, data_fim) for e in empresas_nomes])

        mapa_bancos, todas_receitas, todas_despesas, total_saldo_banco = {}, [], [], 0

        for r in resultados:
            for b in r[0]:
                chave = identificar_banco_principal(b["nome"])
                if chave not in mapa_bancos: mapa_bancos[chave] = {"nome": chave, "saldo": 0}
                mapa_bancos[chave]["saldo"] += b["saldo"]
                total_saldo_banco += b["saldo"]
            todas_receitas.extend(r[1]); todas_despesas.extend(r[2])

        df = pd.DataFrame(index=pd.date_range(start=data_inicio, end=data_fim).strftime('%Y-%m-%d'))
        for col, lista in [("receitas", todas_receitas), ("despesas", todas_despesas)]:
            if lista:
                df_t = pd.DataFrame(lista)
                df_t['data'] = pd.to_datetime(df_t['data']).dt.strftime('%Y-%m-%d')
                df[col] = df_t.groupby("data")["valor"].sum()
            else: df[col] = 0

        df = df.fillna(0)
        df["saldo_projetado"] = total_saldo_banco + (df["receitas"] - df["despesas"]).cumsum()

        return {
            "labels": [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in df.index],
            "receitas": [round(x, 2) for x in df["receitas"].tolist()],
            "despesas": [round(x, 2) for x in df["despesas"].tolist()],
            "saldo": [round(x, 2) for x in df["saldo_projetado"].tolist()],
            "saldos_por_banco": sorted(list(mapa_bancos.values()), key=lambda x: x['nome']),
            "resumo": {
                "banco": round(total_saldo_banco, 2), "total_rec": round(df["receitas"].sum(), 2),
                "total_desp": round(df["despesas"].sum(), 2),
                "saldo_final": round(df["saldo_projetado"].iloc[-1], 2) if not df.empty else round(total_saldo_banco, 2)
            }
        }
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

# --- ENDPOINTS ---

@app.get("/api/empresas")
async def listar_empresas():
    res = supabase.table("tokens").select("empresa, status").order("empresa").execute()
    return [{"nome": r["empresa"], "status": r.get("status", "ATIVO")} for r in res.data]

@app.get("/api/dados")
async def rota_dados(empresa: str, data_inicio: str, data_fim: str):
    return await get_dashboard_data(empresa, data_inicio, data_fim)

@app.post("/api/exportar-pdf")
async def exportar_pdf(request: ExportarRequest):
    dados = await get_dashboard_data(request.empresa, request.data_inicio, request.data_fim)
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    fmt_br = lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Estética do Layout
    cor_primaria = colors.HexColor("#1E293B")
    cor_texto_claro = colors.white
    cor_fundo_cinza = colors.HexColor("#F8FAFC")

    # Cabeçalho Estilizado
    p.setFillColor(cor_primaria)
    p.rect(0, altura - 100, largura, 100, fill=1, stroke=0)
    p.setFillColor(cor_texto_claro)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, altura - 45, "RELATÓRIO FINANCEIRO PROJETADO")
    p.setFont("Helvetica", 10)
    p.drawString(50, altura - 65, f"Cliente: {request.empresa.upper()}")
    p.drawString(50, altura - 80, f"Período: {request.data_inicio} até {request.data_fim}")

    # Rodapé
    p.setFont("Helvetica-Oblique", 8)
    p.setFillColor(colors.gray)
    p.drawString(50, 30, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | JRM Gestão - BPO Financeiro")

    y = altura - 140

    # Inserção do Gráfico
    if request.chart_image:
        try:
            img_data = base64.b64decode(request.chart_image.split(",", 1)[1])
            p.drawImage(ImageReader(io.BytesIO(img_data)), 50, y - 220, width=500, height=200, preserveAspectRatio=True)
            y -= 250
        except: pass

    # Bloco Resumo
    p.setFillColor(cor_fundo_cinza)
    p.roundRect(50, y - 100, 495, 100, 5, fill=1, stroke=0)
    p.setFillColor(cor_primaria)
    p.setFont("Helvetica-Bold", 12); p.drawString(65, y - 25, "RESUMO EXECUTIVO")
    
    p.setFont("Helvetica", 11)
    resumo = dados["resumo"]
    p.drawString(65, y - 45, "Disponibilidade Bancária:"); p.drawRightString(525, y - 45, fmt_br(resumo['banco']))
    p.drawString(65, y - 60, "(+) Previsão de Receitas:"); p.drawRightString(525, y - 60, fmt_br(resumo['total_rec']))
    p.drawString(65, y - 75, "(-) Previsão de Despesas:"); p.drawRightString(525, y - 75, fmt_br(resumo['total_desp']))
    
    p.setFont("Helvetica-Bold", 11); p.setFillColor(colors.HexColor("#0F172A"))
    p.drawString(65, y - 90, "SALDO FINAL PROJETADO:"); p.drawRightString(525, y - 90, fmt_br(resumo['saldo_final']))

    # Bloco Detalhamento Bancário
    y -= 140
    p.setFillColor(cor_primaria)
    p.setFont("Helvetica-Bold", 12); p.drawString(50, y, "DETALHAMENTO POR INSTITUIÇÃO")
    p.line(50, y - 5, 545, y - 5)
    
    y -= 25
    p.setFont("Helvetica", 10)
    for b in dados["saldos_por_banco"]:
        # Se for Itaú, o ícone visual ou cor poderia entrar aqui
        p.drawString(65, y, b['nome'])
        p.drawRightString(525, y, fmt_br(b['saldo']))
        y -= 20
        if y < 100: p.showPage(); y = altura - 50

    p.showPage(); p.save()
    return Response(content=buffer.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=relatorio_{request.empresa}.pdf"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
