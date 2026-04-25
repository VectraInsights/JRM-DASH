from fastapi import FastAPI
import requests
import base64
import pandas as pd
import os
import json
from datetime import datetime, timedelta

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/dados")
def dados(empresa: str, dias: int = 7):
    hoje = datetime.now().date()
    data_ini = hoje
    data_fim = hoje + timedelta(days=dias)

    # 🔴 MOCK inicial (pra subir rápido)
    # depois a gente pluga sua lógica real
    datas = pd.date_range(data_ini, data_fim)

    return {
        "datas": [d.strftime("%Y-%m-%d") for d in datas],
        "receber": [1000 + i*50 for i in range(len(datas))],
        "pagar": [800 + i*30 for i in range(len(datas))],
    }
