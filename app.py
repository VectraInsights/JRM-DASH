import streamlit as st
import pandas as pd
import requests
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# =========================
# CONFIG
# =========================
CONTA_AZUL_CLIENT_ID = "SEU_CLIENT_ID"
CONTA_AZUL_CLIENT_SECRET = "SEU_CLIENT_SECRET"

SHEET_URL = "https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit?gid=0#gid=0"

# =========================
# GOOGLE SHEETS
# =========================
def conectar_google_sheets():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_name(
        "credentials.json", scope
    )

    client = gspread.authorize(creds)
    sheet = client.open_by_url(SHEET_URL).sheet1

    data = sheet.get_all_records()
    return pd.DataFrame(data)


# =========================
# CONTA AZUL - AUTH
# =========================
def gerar_access_token(refresh_token):
    url = "https://api.contaazul.com/oauth2/token"

    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": CONTA_AZUL_CLIENT_ID,
        "client_secret": CONTA_AZUL_CLIENT_SECRET
    }

    response = requests.post(url, data=payload)

    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        st.error(f"Erro ao gerar token: {response.text}")
        return None


# =========================
# BUSCAR DADOS
# =========================
def buscar_contas(access_token, tipo="receber"):
    if tipo == "receber":
        url = "https://api.contaazul.com/v1/financeiro/contas-a-receber"
    else:
        url = "https://api.contaazul.com/v1/financeiro/contas-a-pagar"

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        return response.json()
    else:
        return []


# =========================
# PROCESSAMENTO
# =========================
def processar_dados(empresas_df):
    dados_gerais = []

    for _, row in empresas_df.iterrows():
        empresa = row["empresa"]
        refresh_token = row["refresh_token"]

        access_token = gerar_access_token(refresh_token)

        if not access_token:
            continue

        contas_receber = buscar_contas(access_token, "receber")
        contas_pagar = buscar_contas(access_token, "pagar")

        for c in contas_receber:
            dados_gerais.append({
                "empresa": empresa,
                "tipo": "Receber",
                "valor": c.get("valor", 0),
                "data": c.get("dataVencimento")
            })

        for c in contas_pagar:
            dados_gerais.append({
                "empresa": empresa,
                "tipo": "Pagar",
                "valor": c.get("valor", 0),
                "data": c.get("dataVencimento")
            })

    return pd.DataFrame(dados_gerais)


# =========================
# DASHBOARD
# =========================
def dashboard(df):
    st.title("📊 Dashboard Financeiro")

    if df.empty:
        st.warning("Sem dados")
        return

    col1, col2 = st.columns(2)

    total_receber = df[df["tipo"] == "Receber"]["valor"].sum()
    total_pagar = df[df["tipo"] == "Pagar"]["valor"].sum()

    col1.metric("💰 A Receber", f"R$ {total_receber:,.2f}")
    col2.metric("💸 A Pagar", f"R$ {total_pagar:,.2f}")

    st.divider()

    st.subheader("Por Empresa")
    resumo = df.groupby(["empresa", "tipo"])["valor"].sum().unstack().fillna(0)

    st.dataframe(resumo)

    st.subheader("Detalhado")
    st.dataframe(df)


# =========================
# APP
# =========================
def main():
    st.set_page_config(layout="wide")

    st.sidebar.title("⚙️ Configuração")

    if st.sidebar.button("Atualizar dados"):
        st.cache_data.clear()

    empresas_df = conectar_google_sheets()
    df = processar_dados(empresas_df)

    dashboard(df)


if __name__ == "__main__":
    main()
