import streamlit as st
import requests
import base64
import pandas as pd
import gspread
import plotly.graph_objects as go
from datetime import datetime, timedelta
import streamlit.components.v1 as components
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIG ---
st.set_page_config(page_title="Fluxo de Caixa JRM", layout="wide", initial_sidebar_state="collapsed")

# --- CSS ---
st.markdown("""
<style>
footer {display:none}
</style>
""", unsafe_allow_html=True)

# --- FUNÇÕES ---
@st.cache_resource
def get_sheet():
    try:
        scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
        creds_info = st.secrets["google_sheets"].to_dict()
        creds_info["private_key"] = creds_info["private_key"].replace("\\n","\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
        client = gspread.authorize(creds)
        return client.open_by_url("https://docs.google.com/spreadsheets/d/10vGoOF-_qGTrmoCrUipQC3pmSXkL8QeUk7AI0tVWjao/edit").sheet1
    except:
        return None

def format_br(v):
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X','.')

def obter_token(emp):
    sh = get_sheet()
    if not sh: return None
    try:
        cell = sh.find(emp)
        rt = sh.cell(cell.row,2).value
        ca = st.secrets["conta_azul"]
        auth = base64.b64encode(f"{ca['client_id']}:{ca['client_secret']}".encode()).decode()

        res = requests.post("https://auth.contaazul.com/oauth2/token",
            headers={"Authorization":f"Basic {auth}","Content-Type":"application/x-www-form-urlencoded"},
            data={"grant_type":"refresh_token","refresh_token":rt})

        if res.status_code==200:
            d=res.json()
            return d['access_token']
    except:
        return None

def buscar(endpoint, tk, params):
    out=[]
    params.update({"status":"EM_ABERTO","tamanho_pagina":100,"pagina":1})
    while True:
        r=requests.get(f"https://api-v2.contaazul.com{endpoint}",headers={"Authorization":f"Bearer {tk}"},params=params)
        if r.status_code!=200: break
        itens=r.json().get("itens",[])
        if not itens: break
        for i in itens:
            saldo=i.get("total",0)-i.get("pago",0)
            if saldo>0:
                out.append({"Vencimento":i.get("data_vencimento"),"Valor":saldo})
        if len(itens)<100: break
        params["pagina"]+=1
    return out

# --- CLIENTES ---
sh=get_sheet()
clientes=[r[0] for r in sh.get_all_values()[1:]] if sh else []

# --- SIDEBAR ---
with st.sidebar:
    empresa=st.selectbox("Empresa",["Todos"]+clientes)

    hoje=datetime.now().date()
    ini_pad=hoje
    fim_pad=hoje+timedelta(days=7)

    data_js=components.html(f"""
    <script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
    <script src="https://npmcdn.com/flatpickr/dist/l10n/pt.js"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">

    <input id="d" style="width:100%;padding:8px"/>

    <script>
    flatpickr("#d",{{
        mode:"range",
        dateFormat:"Y-m-d",
        locale:"pt",
        defaultDate:["{ini_pad}","{fim_pad}"],
        onChange:function(d){{
            if(d.length==2){{
                const v=d[0].toISOString().split('T')[0]+"|"+d[1].toISOString().split('T')[0];
                window.location.search="?range="+v;
            }}
        }}
    }});
    </script>
    """,height=80)

    # 🔥 pega via URL (funciona sempre)
    params=st.query_params
    if "range" in params:
        try:
            ini_str,fim_str=params["range"].split("|")
            data_ini=datetime.fromisoformat(ini_str).date()
            data_fim=datetime.fromisoformat(fim_str).date()
        except:
            data_ini=ini_pad
            data_fim=fim_pad
    else:
        data_ini=ini_pad
        data_fim=fim_pad

    exibir_receitas=st.checkbox("Receitas",True)
    exibir_despesas=st.checkbox("Despesas",True)
    exibir_saldo=st.checkbox("Saldo",True)

# --- DADOS ---
alvo=clientes if empresa=="Todos" else [empresa]
p_total=[]
r_total=[]

for emp in alvo:
    tk=obter_token(emp)
    if tk:
        params={"data_vencimento_de":data_ini.isoformat(),"data_vencimento_ate":data_fim.isoformat()}
        p_total+=buscar("/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar",tk,params.copy())
        r_total+=buscar("/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",tk,params.copy())

# --- PROCESSAMENTO ---
df=pd.DataFrame({'data':pd.date_range(data_ini,data_fim)})
df['data_str']=df['data'].dt.strftime('%Y-%m-%d')

if p_total:
    vp=pd.DataFrame(p_total).groupby('Vencimento')['Valor'].sum()
    df['Pagar']=df['data_str'].map(vp).fillna(0)
else:
    df['Pagar']=0

if r_total:
    vr=pd.DataFrame(r_total).groupby('Vencimento')['Valor'].sum()
    df['Receber']=df['data_str'].map(vr).fillna(0)
else:
    df['Receber']=0

df['Saldo']=df['Receber']-df['Pagar']

# --- CARDS ---
c1,c2,c3=st.columns(3)

if exibir_receitas:
    c1.markdown(f"<h3 style='color:#2ecc71'>{format_br(df['Receber'].sum())}</h3>Receber",unsafe_allow_html=True)

if exibir_despesas:
    c2.markdown(f"<h3 style='color:#e74c3c'>{format_br(-df['Pagar'].sum())}</h3>Pagar",unsafe_allow_html=True)

if exibir_saldo:
    cor="#2ecc71" if df['Saldo'].sum()>=0 else "#e74c3c"
    c3.markdown(f"<h3 style='color:{cor}'>{format_br(df['Saldo'].sum())}</h3>Saldo",unsafe_allow_html=True)

# --- GRÁFICO ---
fig=go.Figure()

if exibir_receitas:
    fig.add_bar(x=df['data'],y=df['Receber'],name="Receitas")

if exibir_despesas:
    fig.add_bar(x=df['data'],y=df['Pagar'],name="Despesas")

if exibir_saldo:
    fig.add_scatter(x=df['data'],y=df['Saldo'],mode="lines+markers",name="Saldo")

fig.update_layout(
    xaxis=dict(tickformat="%d/%m"),
    hovermode="x unified"
)

st.plotly_chart(fig,use_container_width=True,config={'displayModeBar':False})
