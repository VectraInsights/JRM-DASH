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

@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
    http_client = httpx.AsyncClient(limits=limits, timeout=30.0)
    yield
    await http_client.aclose()

app = FastAPI(lifespan=lifespan, title="API JRM Gestão")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Configuração Supabase/Conta Azul
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
CLIENT_ID = os.environ.get("CONTA_AZUL_CLIENT_ID")
CLIENT_SECRET = os.environ.get("CONTA_AZUL_CLIENT_SECRET")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Mapeamento de Logos (Ajuste os caminhos locais aqui)
LOGOS_BANCOS = {
    "ITAÚ": "assets/logos/itau.png",
    "BRADESCO": "assets/logos/bradesco.png",
    "SICOOB": "assets/logos/sicoob.png"
}

def remover_acentos(texto: str) -> str:
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def identificar_banco_principal(nome_raw: str) -> str:
    nome = remover_acentos(nome_raw).upper()
    if "ITAU" in nome: return "ITAÚ"
    if "BRADESCO" in nome: return "BRADESCO"
    if "SICOOB" in nome: return "SICOOB"
    return nome_raw.upper()

# --- LÓGICA DE TOKENS (REDUZIDA PARA O EXEMPLO) ---
async def obter_token_atual(empresa_nome: str):
    # (Mantenha sua lógica de renovação de token aqui conforme o código anterior)
    res = supabase.table("tokens").select("access_token").eq("empresa", empresa_nome).execute()
    return res.data[0]["access_token"] if res.data else None

# --- BUSCAS ---
async def buscar_v2_async(endpoint: str, empresa_nome: str, params: dict):
    token = await obter_token_atual(empresa_nome)
    if not token: return []
    itens_acumulados, p = [], {**params, "status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1}
    try:
        headers = {"Authorization": f"Bearer {token}"}
        res = await http_client.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p)
        itens = res.json().get('itens', [])
        for i in itens:
            dt_venc = i.get("data_vencimento")[:10]
            valor_aberto = i.get('total', 0) - i.get('pago', 0)
            if valor_aberto > 0: itens_acumulados.append({"data": dt_venc, "valor": valor_aberto})
    except: pass
    return itens_acumulados

async def buscar_saldos_async(token: str):
    headers = {"Authorization": f"Bearer {token}"}
    lista_bancos = []
    try:
        res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
        contas = res.json()
        for conta in contas:
            nome_raw = conta.get('nome', '')
            nome_limpo = remover_acentos(nome_raw).upper()
            if any(b in nome_limpo for b in ["ITAU", "BRADESCO", "SICOOB"]) and " AP." not in nome_limpo:
                url_saldo = f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual"
                r_saldo = await http_client.get(url_saldo, headers=headers)
                lista_bancos.append({"nome": nome_raw, "saldo": r_saldo.json().get('saldo_atual', 0)})
    except: pass
    return lista_bancos

# --- DADOS DASHBOARD ---
async def get_dashboard_data(empresa: str, data_inicio: str, data_fim: str):
    token = await obter_token_atual(empresa)
    params = {"data_vencimento_de": data_inicio, "data_vencimento_ate": data_fim}
    
    saldos_brutos, rec, pag = await asyncio.gather(
        buscar_saldos_async(token),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar", empresa, params),
        buscar_v2_async("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar", empresa, params)
    )

    mapa_bancos, total_banco = {}, 0
    for b in saldos_brutos:
        chave = identificar_banco_principal(b["nome"])
        if chave not in mapa_bancos: mapa_bancos[chave] = {"nome": chave, "saldo": 0}
        mapa_bancos[chave]["saldo"] += b["saldo"]
        total_banco += b["saldo"]

    df = pd.DataFrame(index=pd.date_range(start=data_inicio, end=data_fim).strftime('%Y-%m-%d'))
    # ... (Processamento de df receitas/despesas igual ao anterior)
    
    return {
        "labels": [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in df.index],
        "receitas": [round(x, 2) for x in df.get("receitas", [0]*len(df))],
        "despesas": [round(x, 2) for x in df.get("despesas", [0]*len(df))],
        "saldo": [round(x, 2) for x in df.get("saldo_projetado", [0]*len(df))],
        "saldos_por_banco": list(mapa_bancos.values()),
        "resumo": {"banco": total_banco, "total_rec": 0, "total_desp": 0, "saldo_final": 0} # Simplificado
    }

# --- PDF MELHORADO COM LOGOS ---
@app.post("/api/exportar-pdf")
async def exportar_pdf(request: ExportarRequest):
    dados = await get_dashboard_data(request.empresa, request.data_inicio, request.data_fim)
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4
    fmt_br = lambda v: f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Cabeçalho Dark
    p.setFillColor(colors.HexColor("#1E293B"))
    p.rect(0, altura - 100, largura, 100, fill=1, stroke=0)
    p.setFillColor(colors.white)
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, altura - 50, "FLUXO DE CAIXA PROJETADO")
    
    # Gráfico
    if request.chart_image:
        img_data = base64.b64decode(request.chart_image.split(",", 1)[1])
        p.drawImage(ImageReader(io.BytesIO(img_data)), 50, altura - 350, width=500, height=230)

    # Detalhamento por Banco com Logos
    y = altura - 400
    p.setFillColor(colors.black)
    p.setFont("Helvetica-Bold", 12); p.drawString(50, y, "SALDOS POR INSTITUIÇÃO")
    p.line(50, y-5, 545, y-5)
    y -= 30

    for b in dados["saldos_por_banco"]:
        nome_banco = b['nome']
        # Desenha Logo se existir
        caminho_logo = LOGOS_BANCOS.get(nome_banco)
        if caminho_logo and os.path.exists(caminho_logo):
            try:
                p.drawImage(caminho_logo, 55, y - 5, width=15, height=15, preserveAspectRatio=True, mask='auto')
            except: pass
        
        p.setFont("Helvetica", 10)
        p.drawString(75, y, nome_banco)
        p.drawRightString(525, y, fmt_br(b['saldo']))
        y -= 25

    p.showPage(); p.save()
    return Response(content=buffer.getvalue(), media_type="application/pdf")
