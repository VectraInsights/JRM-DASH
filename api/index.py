from fastapi import FastAPI, Query
import requests
import base64
import pandas as pd
import os
import json
import unicodedata
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# 🔥 CACHE SIMPLES (substitui st.cache_resource)
sheet_cache = {"conn": None, "time": None}

def get_sheet():
    global sheet_cache

    if sheet_cache["conn"]:
        return sheet_cache["conn"]

    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']

    creds_raw = os.environ.get("GOOGLE_SHEETS_JSON")
    creds_dict = json.loads(creds_raw)
    creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    sheet = client.open_by_url(
        "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit#gid=0"
    ).sheet1

    sheet_cache["conn"] = sheet
    return sheet


def listar_clientes():
    sh = get_sheet()
    rows = sh.get_all_values()
    return [r[0] for r in rows[1:]]


def obter_token(empresa_nome):
    sh = get_sheet()
    cell = sh.find(empresa_nome)

    refresh_token = sh.cell(cell.row, 2).value

    cid = os.environ.get("CONTA_AZUL_CLIENT_ID")
    cs = os.environ.get("CONTA_AZUL_CLIENT_SECRET")

    auth = base64.b64encode(f"{cid}:{cs}".encode()).decode()

    res = requests.post(
        "https://auth.contaazul.com/oauth2/token",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token
        },
        timeout=10
    )

    if res.status_code == 200:
        data = res.json()

        if data.get("refresh_token"):
            sh.update_cell(cell.row, 2, data["refresh_token"])

        return data["access_token"]

    return None


def buscar_v2(endpoint, token, params):
    itens_acum = []
    headers = {"Authorization": f"Bearer {token}"}

    params.update({
        "status": "EM_ABERTO",
        "tamanho_pagina": 100,
        "pagina": 1
    })

    while True:
        res = requests.get(
            f"https://api-v2.contaazul.com{endpoint}",
            headers=headers,
            params=params,
            timeout=10
        )

        if res.status_code != 200:
            break

        itens = res.json().get("itens", [])
        if not itens:
            break

        for i in itens:
            saldo = i.get("total", 0) - i.get("pago", 0)
            if saldo > 0:
                itens_acum.append({
                    "data": i.get("data_vencimento"),
                    "valor": saldo
                })

        if len(itens) < 100:
            break

        params["pagina"] += 1

    return itens_acum


def buscar_saldo(token):
    headers = {"Authorization": f"Bearer {token}"}
    total = 0

    bancos = ["ITAU", "BRADESCO", "SICOOB"]

    def normalize(txt):
        return "".join(
            c for c in unicodedata.normalize('NFD', txt)
            if unicodedata.category(c) != 'Mn'
        )

    res = requests.get(
        "https://api-v2.contaazul.com/v1/conta-financeira",
        headers=headers,
        timeout=10
    )

    if res.status_code == 200:
        for conta in res.json().get("itens", []):
            nome = normalize(conta.get("nome", "")).upper()

            if any(b in nome for b in bancos):
                r = requests.get(
                    f"https://api-v2.contaazul.com/v1/conta-financeira/{conta['id']}/saldo-atual",
                    headers=headers,
                    timeout=5
                )

                if r.status_code == 200:
                    total += r.json().get("saldo_atual", 0)

    return total


@app.get("/clientes")
def clientes():
    return listar_clientes()


@app.get("/dados")
def dados(
    empresa: str = Query(...),
    dias: int = Query(7)
):
    hoje = datetime.now().date()
    data_ini = hoje
    data_fim = hoje + timedelta(days=dias)

    token = obter_token(empresa)
    if not token:
        return {"erro": "token"}

    saldo = buscar_saldo(token)

    params = {
        "data_vencimento_de": data_ini.isoformat(),
        "data_vencimento_ate": data_fim.isoformat()
    }

    pagar = buscar_v2(
        "/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar",
        token,
        params.copy()
    )

    receber = buscar_v2(
        "/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",
        token,
        params.copy()
    )

    df = pd.DataFrame({
        "data": pd.date_range(data_ini, data_fim)
    })

    df["data_str"] = df["data"].dt.strftime("%Y-%m-%d")

    df_p = pd.DataFrame(pagar)
    df_r = pd.DataFrame(receber)

    if not df_p.empty:
        df_p = df_p.groupby("data")["valor"].sum()
    if not df_r.empty:
        df_r = df_r.groupby("data")["valor"].sum()

    df["pagar"] = df["data_str"].map(df_p).fillna(0)
    df["receber"] = df["data_str"].map(df_r).fillna(0)

    df["acum"] = saldo + (df["receber"] - df["pagar"]).cumsum()

    return {
        "datas": df["data_str"].tolist(),
        "pagar": df["pagar"].tolist(),
        "receber": df["receber"].tolist(),
        "acumulado": df["acum"].tolist(),
        "saldo": saldo
    }
