import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime

# --- CONFIGURAÇÕES ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

# --- GOOGLE SHEETS ---
def conectar_google_sheets():
    gs = st.secrets["connections"]["gsheets"]
    info = {
        "type": gs["type"],
        "project_id": gs["project_id"],
        "private_key_id": gs["private_key_id"],
        "client_email": gs["client_email"],
        "client_id": gs["client_id"],
        "auth_uri": gs["auth_uri"],
        "token_uri": gs["token_uri"],
        "auth_provider_x509_cert_url": gs["auth_provider_x509_cert_url"],
        "client_x509_cert_url": gs["client_x509_cert_url"]
    }

    b64_key = gs["private_key_base64"]
    info["private_key"] = base64.b64decode(b64_key).decode("utf-8").replace("\\n", "\n")

    creds = Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

    return gspread.authorize(creds).open_by_key(ID_PLANILHA).worksheet("Página1")

# --- TOKEN ---
def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"

    try:
        response = requests.post(
            url,
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token_raw).strip()
            }
        )

        if response.status_code == 200:
            dados = response.json()

            novo_refresh = dados.get("refresh_token")
            if novo_refresh:
                cell = aba_planilha.find(empresa)
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)

            return dados.get("access_token")

        else:
            st.error(f"Erro token {empresa}: {response.text}")
            return None

    except Exception as e:
        st.error(f"Erro token {empresa}: {e}")
        return None

# --- BUSCA COM PAGINAÇÃO ---
def buscar_parcelas_v2(token, tipo):
    url = f"https://api-v2.contaazul.com/v1/financeiro/contas-a-{tipo}/parcelas"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    pagina = 1
    todos_itens = []

    while True:
        params = {
            "pagina": pagina,
            "tamanho_pagina": 100
        }

        try:
            r = requests.get(url, headers=headers, params=params)

            if r.status_code != 200:
                st.warning(f"Erro API ({tipo}): {r.text}")
                break

            data = r.json()
            itens = data.get("itens", [])

            if not itens:
                break

            todos_itens.extend(itens)

            # Debug
            st.write(f"Página {pagina} ({tipo}): {len(itens)} registros")

            if len(itens) < 100:
                break

            pagina += 1

        except Exception as e:
            st.error(f"Erro API ({tipo}): {e}")
            break

    return todos_itens

# --- UI ---
st.set_page_config(page_title="Dashboard Financeiro", layout="wide")
st.title("📊 Totais Financeiros e Gráfico")

if st.button('🚀 Rodar Varredura'):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()

    consolidado = []

    for row in linhas:
        emp = row['empresa']
        refresh_token = row['refresh_token']

        st.divider()
        st.subheader(f"🏢 {emp}")

        token = obter_access_token(emp, refresh_token, aba)

        if not token:
            continue

        for tipo_api, rotulo in [("receber", "Receita"), ("pagar", "Despesa")]:
            itens = buscar_parcelas_v2(token, tipo_api)

            st.write(f"{rotulo}: {len(itens)} registros")

            if not itens:
                st.warning(f"Nenhum dado de {rotulo} para {emp}")
                continue

            for i in itens:
                try:
                    status = str(i.get('status', '')).upper()

                    # Apenas em aberto
                    if status not in ["EM_ABERTO", "VENCIDO", "PARCIAL"]:
                        continue

                    # Valor
                    v_raw = i.get('valor', {})

                    if isinstance(v_raw, dict):
                        val = float(v_raw.get('valor', 0))
                    else:
                        val = float(i.get('valor_nominal', 0))

                    # Data
                    dt_raw = i.get('data_vencimento')
                    if not dt_raw:
                        continue

                    dt_venc = pd.to_datetime(dt_raw).date()

                    consolidado.append({
                        'data': dt_venc,
                        'valor': val,
                        'tipo': rotulo,
                        'unidade': emp
                    })

                except Exception as e:
                    st.warning(f"Erro item: {e}")

    # --- RESULTADOS ---
    if consolidado:
        df = pd.DataFrame(consolidado)

        # Totais
        total_receber = df[df['tipo'] == 'Receita']['valor'].sum()
        total_pagar = df[df['tipo'] == 'Despesa']['valor'].sum()
        saldo = total_receber - total_pagar

        c1, c2, c3 = st.columns(3)

        c1.metric("TOTAL A RECEBER", f"R$ {total_receber:,.2f}")
        c2.metric("TOTAL A PAGAR", f"R$ {total_pagar:,.2f}")
        c3.metric("SALDO EM ABERTO", f"R$ {saldo:,.2f}")

        # Gráfico
        st.subheader("📅 Gráfico de Vencimentos")

        df_g = df.groupby(['data', 'tipo'])['valor'].sum().unstack(fill_value=0)

        for col in ['Receita', 'Despesa']:
            if col not in df_g.columns:
                df_g[col] = 0

        st.bar_chart(df_g[['Receita', 'Despesa']])

        # Tabela
        with st.expander("📋 Ver lista detalhada"):
            st.dataframe(df)

    else:
        st.error("❌ Nenhum dado encontrado. Verifique tokens, permissões ou dados no Conta Azul.")
