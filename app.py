import streamlit as st
import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
ID_PLANILHA = "10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao"
# As chaves abaixo devem estar no secrets do Streamlit
CLIENT_ID = st.secrets["api"]["client_id"]
CLIENT_SECRET = st.secrets["api"]["client_secret"]

def conectar_google_sheets():
    try:
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
        key_decoded = base64.b64decode(b64_key).decode("utf-8")
        info["private_key"] = key_decoded.replace("\\n", "\n")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = Credentials.from_service_account_info(info, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(ID_PLANILHA)

        return spreadsheet.worksheet("Página1")

    except Exception as e:
        st.error(f"❌ Falha técnica na conexão Google: {e}")
        st.stop()


def obter_access_token(empresa, refresh_token_raw, aba_planilha):
    url = "https://auth.contaazul.com/oauth2/token"

    # Limpeza crucial para tokens JWT (longos)
    refresh_token = str(refresh_token_raw).strip()

    if not refresh_token or refresh_token == "None":
        st.error(f"❌ Erro: Refresh Token da {empresa} está vazio ou inválido na planilha!")
        return None

    # Payload atualizado com o escopo obrigatório solicitado pela Conta Azul
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": "openid profile aws.cognito.signin.user.admin"
    }

    try:
        response = requests.post(
            url,
            auth=(CLIENT_ID, CLIENT_SECRET),
            data=payload
        )

        if response.status_code == 200:
            dados = response.json()
            novo_refresh = dados.get("refresh_token")

            # Atualiza o refresh token na planilha imediatamente
            try:
                cell = aba_planilha.find(empresa)
                # Coluna B é col + 1 assumindo que empresa está na A
                aba_planilha.update_cell(cell.row, cell.col + 1, novo_refresh)
            except Exception as e:
                st.warning(f"⚠️ Token renovado, mas falhou ao gravar na planilha: {e}")

            return dados.get("access_token")

        else:
            st.error(f"❌ Falha ao renovar token para {empresa}")
            st.code(response.text) # Mostra o erro 401/400 detalhado
            return None

    except Exception as e:
        st.error(f"❌ Erro de conexão com Conta Azul: {e}")
        return None


def listar_lancamentos_futuros(access_token, empresa_nome):
    url = "https://api.contaazul.com/v1/financials/transactions"

    headers = {
        "Authorization": f"Bearer {access_token}"
    }

    # Range de datas
    data_inicio = (datetime.now() - timedelta(days=7)).date().isoformat()
    data_fim = (datetime.now() + timedelta(days=45)).date().isoformat()

    params = {
        "expiration_start": data_inicio,
        "expiration_end": data_fim
    }

    try:
        st.info(f"📡 Chamando API para {empresa_nome}...")
        r = requests.get(url, headers=headers, params=params)

        if r.status_code == 200:
            res_bruto = r.json()
            itens = res_bruto if isinstance(res_bruto, list) else res_bruto.get('items', [])
            return itens
        else:
            st.error(f"Erro {r.status_code} na API {empresa_nome}: {r.text}")
            return []

    except Exception as e:
        st.error(f"Falha na requisição {empresa_nome}: {e}")
        return []


# --- INTERFACE ---
st.set_page_config(page_title="Dashboard Financeiro JRM", layout="wide")
st.title("📊 Fluxo de Caixa Consolidado (Próximos 45 dias)")

if st.button('🚀 Sincronizar Dados Agora'):
    aba = conectar_google_sheets()

    with st.status("Sincronizando com Conta Azul...", expanded=True) as status:
        lista_dados = aba.get_all_records()
        todos_lancamentos = []

        for row in lista_dados:
            emp = row['empresa']
            token_ref = row['refresh_token']

            st.write(f"🔄 Processando unidade: **{emp}**")

            acc_token = obter_access_token(emp, token_ref, aba)

            if acc_token:
                itens = listar_lancamentos_futuros(acc_token, emp)

                for i in itens:
                    i['unidade'] = emp
                    # Cálculo de valor (alguns endpoints usam amount, outros value)
                    v = i.get('value') if i.get('value') is not None else i.get('amount', 0)
                    i['valor_final'] = v
                    # Identificação de Tipo
                    i['tipo'] = 'Recebível' if i.get('category_group') == 'REVENUE' else 'Pagável'

                todos_lancamentos.extend(itens)
                st.success(f"✅ {emp}: {len(itens)} itens carregados.")
            else:
                st.warning(f"⚠️ {emp} ignorada devido a erro no token.")

        status.update(label="Sincronização Concluída!", state="complete")

    if todos_lancamentos:
        st.divider()
        df = pd.DataFrame(todos_lancamentos)

        # Métricas em colunas
        c1, c2, c3 = st.columns(3)
        receita = df[df['tipo'] == 'Recebível']['valor_final'].sum()
        despesa = df[df['tipo'] == 'Pagável']['valor_final'].sum()

        c1.metric("Total a Receber", f"R$ {receita:,.2f}")
        c2.metric("Total a Pagar", f"R$ {despesa:,.2f}")
        c3.metric("Saldo do Período", f"R$ {(receita - despesa):,.2f}")

        # Tabela formatada
        st.subheader("📋 Detalhamento dos Lançamentos")
        colunas_exibicao = ['due_date', 'description', 'valor_final', 'tipo', 'unidade']
        # Filtra apenas colunas que realmente existem no DF
        cols = [c for c in colunas_exibicao if c in df.columns]
        
        st.dataframe(
            df[cols].sort_values(by='due_date'), 
            use_container_width=True,
            hide_index=True
        )

    else:
        st.error("❌ Nenhum dado foi retornado pela API. Verifique os tokens na planilha.")
