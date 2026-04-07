import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials

# --- CONFIG ---
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

    info["private_key"] = base64.b64decode(gs["private_key_base64"]).decode("utf-8").replace("\\n", "\n")

    creds = Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

    return gspread.authorize(creds).open_by_key(ID_PLANILHA).worksheet("Página1")

# --- TOKEN ---
def obter_access_token(empresa, refresh_token_raw, aba):
    url = "https://auth.contaazul.com/oauth2/token"

    try:
        r = requests.post(
            url,
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={
                "grant_type": "refresh_token",
                "refresh_token": str(refresh_token_raw).strip()
            }
        )

        if r.status_code == 200:
            data = r.json()

            novo_refresh = data.get("refresh_token")
            if novo_refresh:
                cell = aba.find(empresa)
                aba.update_cell(cell.row, cell.col + 1, novo_refresh)

            return data.get("access_token")

        else:
            st.error(f"Erro token {empresa}: {r.text}")
            return None

    except Exception as e:
        st.error(f"Erro token {empresa}: {e}")
        return None

# --- API CERTA (PARCELAS) ---
def buscar_parcelas(token):
    url = "https://api-v2.contaazul.com/api/v1/financeiro/parcelas"

    headers = {
        "Authorization": f"Bearer {token}"
    }

    pagina = 1
    todos = []

    while True:
        params = {
            "pagina": pagina,
            "tamanhoPagina": 100
        }

        try:
            r = requests.get(url, headers=headers, params=params)

            if r.status_code != 200:
                st.error(f"Erro API: {r.text}")
                break

            data = r.json()
            itens = data.get("itens", [])

            if not itens:
                break

            todos.extend(itens)

            st.write(f"Página {pagina}: {len(itens)} registros")

            if len(itens) < 100:
                break

            pagina += 1

        except Exception as e:
            st.error(f"Erro API: {e}")
            break

    return todos

# --- UI ---
st.set_page_config(page_title="Dashboard Financeiro", layout="wide")
st.title("📊 Dashboard Conta Azul (V2 Parcelas)")

if st.button("🚀 Rodar Varredura"):
    aba = conectar_google_sheets()
    linhas = aba.get_all_records()

    consolidado = []

    for row in linhas:
        emp = row["empresa"]
        refresh = row["refresh_token"]

        st.divider()
        st.subheader(f"🏢 {emp}")

        token = obter_access_token(emp, refresh, aba)

        if not token:
            continue

        itens = buscar_parcelas(token)

        st.write(f"Total registros: {len(itens)}")

        for i in itens:
            try:
                tipo = str(i.get("tipo", "")).upper()
                status = str(i.get("status", "")).upper()

                # ignora pagos
                if status in ["PAGO", "QUITADO", "RECEBIDO", "BAIXADO"]:
                    continue

                # define tipo
                if tipo == "RECEBER":
                    rotulo = "Receita"
                elif tipo == "PAGAR":
                    rotulo = "Despesa"
                else:
                    continue

                # valor
                v = i.get("valor")
                if isinstance(v, dict):
                    val = float(v.get("valor", 0))
                else:
                    val = float(v or 0)

                # data
                dt_raw = i.get("dataVencimento") or i.get("data_vencimento")
                if not dt_raw:
                    continue

                dt = pd.to_datetime(dt_raw).date()

                consolidado.append({
                    "data": dt,
                    "valor": val,
                    "tipo": rotulo,
                    "empresa": emp
                })

            except Exception as e:
                st.warning(f"Erro item: {e}")

    # --- RESULTADO ---
    if consolidado:
        df = pd.DataFrame(consolidado)

        tr = df[df["tipo"] == "Receita"]["valor"].sum()
        tp = df[df["tipo"] == "Despesa"]["valor"].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("A RECEBER", f"R$ {tr:,.2f}")
        c2.metric("A PAGAR", f"R$ {tp:,.2f}")
        c3.metric("SALDO", f"R$ {(tr - tp):,.2f}")

        st.subheader("📅 Vencimentos")
        df_g = df.groupby(["data", "tipo"])["valor"].sum().unstack(fill_value=0)
        st.bar_chart(df_g)

        with st.expander("Detalhes"):
            st.dataframe(df)

    else:
        st.error("❌ Nenhum dado encontrado")
