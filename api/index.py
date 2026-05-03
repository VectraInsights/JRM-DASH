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

# --- IMPORTAÇÕES PARA PDF PROFISSIONAL ---
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
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

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- UTILITÁRIOS ---
def remover_acentos(texto: str) -> str:
    if not texto: return ""
    return "".join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def fmt_br(valor):
    """Formata moeda para o padrão brasileiro R$ 1.234,56"""
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- LÓGICA DE NEGÓCIO (CONTA AZUL) ---
# (Mantida a lógica original de busca e tokens para garantir o funcionamento)

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
            novo_access = dados.get("access_token")
            supabase.table("tokens").update({
                "access_token": novo_access,
                "refresh_token": dados.get("refresh_token"),
                "status": "ATIVO",
                "updated_at": datetime.now().isoformat()
            }).eq("empresa", empresa_nome).execute()
            return novo_access
        return None
    except: return None

async def obter_token_atual(empresa_nome: str):
    res = supabase.table("tokens").select("access_token, status").eq("empresa", empresa_nome).execute()
    if res.data and res.data[0].get("status") == "ATIVO":
        return res.data[0]["access_token"]
    return await renovar_e_obter_novo_token(empresa_nome)

async def buscar_v2_async(endpoint: str, empresa_nome: str, params: dict):
    token = await obter_token_atual(empresa_nome)
    if not token: return []
    itens_acumulados = []
    p = {**params, "status": "EM_ABERTO", "tamanho_pagina": 100, "pagina": 1}
    for _ in range(2):
        headers = {"Authorization": f"Bearer {token}"}
        res = await http_client.get(f"https://api-v2.contaazul.com{endpoint}", headers=headers, params=p)
        if res.status_code == 401:
            token = await renovar_e_obter_novo_token(empresa_nome)
            continue
        if res.status_code != 200: break
        dados = res.json()
        itens = dados.get('itens', [])
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
    lista_bancos = []
    bancos_permitidos = ["ITAU", "BRADESCO", "SICOOB"]
    try:
        res = await http_client.get("https://api-v2.contaazul.com/v1/conta-financeira", headers=headers)
        if res.status_code == 200:
            contas = res.json() if isinstance(res.json(), list) else res.json().get('itens', [])
            tarefas, nomes = [], []
            for conta in contas:
                nome_limpo = remover_acentos(conta.get('nome', '')).upper()
                if any(b in nome_limpo for b in bancos_permitidos) and " AP." not in nome_limpo:
                    url_saldo = f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual"
                    tarefas.append(http_client.get(url_saldo, headers=headers))
                    nomes.append(conta.get('nome', ''))
            respostas = await asyncio.gather(*tarefas, return_exceptions=True)
            for i, r in enumerate(respostas):
                if isinstance(r, httpx.Response) and r.status_code == 200:
                    lista_bancos.append({"nome": nomes[i], "saldo": round(r.json().get('saldo_atual', 0), 2)})
    except: pass
    return lista_bancos

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
    BANCOS_EXCLUSIVOS = ["ITAU", "BRADESCO", "SICOOB"]
    if empresa.lower() == "todas":
        res_emp = supabase.table("tokens").select("empresa").execute()
        empresas_nomes = [r["empresa"] for r in res_emp.data]
    else:
        empresas_nomes = [empresa.strip()]
    
    resultados = await asyncio.gather(*[processar_empresa(e, data_inicio, data_fim) for e in empresas_nomes])
    
    mapa_bancos, todas_receitas, todas_despesas, total_saldo_banco = {}, [], [], 0
    for r in resultados:
        for b in r[0]:
            nome_up = remover_acentos(b["nome"]).upper()
            if any(p in nome_up for p in BANCOS_EXCLUSIVOS):
                mapa_bancos[nome_up] = {"nome": b["nome"], "saldo": mapa_bancos.get(nome_up, {"saldo":0})["saldo"] + b["saldo"]}
                total_saldo_banco += b["saldo"]
        todas_receitas.extend(r[1])
        todas_despesas.extend(r[2])
    
    df = pd.DataFrame(index=pd.date_range(start=data_inicio, end=data_fim).strftime('%Y-%m-%d'))
    df["receitas"] = pd.DataFrame(todas_receitas).groupby("data")["valor"].sum() if todas_receitas else 0
    df["despesas"] = pd.DataFrame(todas_despesas).groupby("data")["valor"].sum() if todas_despesas else 0
    df = df.fillna(0)
    df["saldo_projetado"] = total_saldo_banco + (df["receitas"] - df["despesas"]).cumsum()

    return {
        "saldos_por_banco": sorted(list(mapa_bancos.values()), key=lambda x: x['nome']),
        "resumo": {
            "banco": round(total_saldo_banco, 2),
            "total_rec": round(df["receitas"].sum(), 2),
            "total_desp": round(df["despesas"].sum(), 2),
            "saldo_final": round(df["saldo_projetado"].iloc[-1], 2) if not df.empty else round(total_saldo_banco, 2)
        }
    }

# --- ENDPOINT DE EXPORTAÇÃO (NOVO DESIGN) ---
@app.post("/api/exportar-pdf")
async def exportar_pdf(request: ExportarRequest):
    dados = await get_dashboard_data(request.empresa, request.data_inicio, request.data_fim)
    buffer = BytesIO()
    
    # Configuração do Documento
    doc = SimpleDocTemplate(
        buffer, 
        pagesize=A4, 
        rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40
    )
    styles = getSampleStyleSheet()
    elementos = []

    # --- ESTILOS ---
    style_titulo = ParagraphStyle(
        'Titulo', parent=styles['Heading1'], fontSize=20, 
        textColor=colors.hexColor("#1A237E"), spaceAfter=14
    )
    style_sub = ParagraphStyle(
        'Sub', parent=styles['Normal'], fontSize=11, textColor=colors.grey
    )
    style_secao = ParagraphStyle(
        'Secao', parent=styles['Heading2'], fontSize=14, 
        textColor=colors.hexColor("#1A237E"), spaceBefore=20, spaceAfter=12
    )

    # --- CONTEÚDO ---
    # Cabeçalho
    elementos.append(Paragraph("RELATÓRIO FINANCEIRO PROJETADO", style_titulo))
    elementos.append(Paragraph(f"<b>Cliente:</b> {request.empresa.upper()}", style_sub))
    elementos.append(Paragraph(f"<b>Período Analisado:</b> {request.data_inicio} até {request.data_fim}", style_sub))
    elementos.append(Paragraph(f"<b>Data de Emissão:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}", style_sub))
    elementos.append(Spacer(1, 20))

    # Gráfico
    if request.chart_image:
        try:
            img_data = base64.b64decode(request.chart_image.split(",")[1])
            img_buffer = io.BytesIO(img_data)
            img = Image(img_buffer, width=500, height=230)
            img.hAlign = 'CENTER'
            elementos.append(img)
            elementos.append(Spacer(1, 25))
        except: pass

    # Tabela 1: Resumo
    elementos.append(Paragraph("1. Resumo Consolidado", style_secao))
    res = dados["resumo"]
    data_resumo = [
        ["Indicador Financeiro", "Valor"],
        ["Saldo Disponível Atual (Bancos Selecionados)", fmt_br(res['banco'])],
        ["Projeção de Receitas (Contas a Receber)", fmt_br(res['total_rec'])],
        ["Projeção de Despesas (Contas a Pagar)", fmt_br(res['total_desp'])],
        ["Saldo Final Projetado para o Período", fmt_br(res['saldo_final'])]
    ]
    
    t_resumo = Table(data_resumo, colWidths=[360, 140])
    t_resumo.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.hexColor("#1A237E")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, -1), (-1, -1), colors.hexColor("#E8EAF6")), # Cor de destaque no saldo final
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    elementos.append(t_resumo)

    # Tabela 2: Bancos
    elementos.append(Paragraph("2. Detalhamento por Instituição", style_secao))
    data_bancos = [["Instituição Financeira", "Saldo Atual"]]
    for b in dados["saldos_por_banco"]:
        data_bancos.append([b['nome'], fmt_br(b['saldo'])])

    t_bancos = Table(data_bancos, colWidths=[360, 140])
    t_bancos.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.hexColor("#455A64")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.silver),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.hexColor("#F5F5F5")]), # Efeito Zebra
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elementos.append(t_bancos)

    # Geração
    doc.build(elementos)
    pdf_out = buffer.getvalue()
    buffer.close()
    
    return Response(
        content=pdf_out, 
        media_type="application/pdf", 
        headers={"Content-Disposition": f"attachment; filename=relatorio_{request.empresa}.pdf"}
    )

@app.get("/api/empresas")
async def listar_empresas():
    res = supabase.table("tokens").select("empresa, status").order("empresa").execute()
    return [{"nome": r["empresa"], "status": r.get("status", "ATIVO")} for r in res.data]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
