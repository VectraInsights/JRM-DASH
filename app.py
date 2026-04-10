import streamlit as st
import pandas as pd
from datetime import datetime

# ====================== CONFIGURAÇÕES ======================
st.set_page_config(page_title="BPO Dashboard", layout="wide")

# Inicializa session_state
if 'empresas' not in st.session_state:
    st.session_state.empresas = []          # lista de dicts
if 'empresa_selecionada' not in st.session_state:
    st.session_state.empresa_selecionada = None
if 'modo_edicao' not in st.session_state:
    st.session_state.modo_edicao = False

# ====================== SIDEBAR - GERENCIAMENTO DE EMPRESAS ======================
st.sidebar.title("Empresas")

# --- Botão para adicionar nova empresa ---
if st.sidebar.button("➕ Nova Empresa", use_container_width=True):
    st.session_state.modo_edicao = True
    st.session_state.empresa_selecionada = None   # indica que é uma nova empresa

# Lista de empresas existentes
if st.session_state.empresas:
    empresa_nomes = [emp["nome"] for emp in st.session_state.empresas]
    empresa_selecionada = st.sidebar.selectbox(
        "Empresa Atual",
        options=empresa_nomes,
        index=empresa_nomes.index(st.session_state.empresa_selecionada) 
              if st.session_state.empresa_selecionada in empresa_nomes else 0
    )
    st.session_state.empresa_selecionada = empresa_selecionada
else:
    st.sidebar.info("Nenhuma empresa cadastrada ainda.")

# ====================== FORMULÁRIO DE NOVA/EDIÇÃO DE EMPRESA ======================
if st.session_state.modo_edicao:
    st.subheader("Nova Empresa" if not st.session_state.empresa_selecionada else f"Editando: {st.session_state.empresa_selecionada}")

    with st.form("form_empresa"):
        nome_atual = st.session_state.empresa_selecionada if st.session_state.empresa_selecionada else ""
        
        nome_empresa = st.text_input("Nome da Empresa *", value=nome_atual, key="nome_input")
        
        col1, col2 = st.columns(2)
        with col1:
            cnpj = st.text_input("CNPJ", key="cnpj_input")
        with col2:
            responsavel = st.text_input("Responsável", key="resp_input")
        
        observacao = st.text_area("Observações", key="obs_input")
        
        submitted = st.form_submit_button("Salvar Empresa")
        
        if submitted:
            if not nome_empresa.strip():
                st.error("Nome da empresa é obrigatório!")
            else:
                # Verifica se já existe empresa com esse nome (exceto se for edição)
                if (not st.session_state.empresa_selecionada or 
                    nome_empresa != st.session_state.empresa_selecionada):
                    if any(emp["nome"].upper() == nome_empresa.upper() for emp in st.session_state.empresas):
                        st.error("Já existe uma empresa com esse nome!")
                        st.stop()
                
                nova_empresa = {
                    "nome": nome_empresa.strip(),
                    "cnpj": cnpj.strip(),
                    "responsavel": responsavel.strip(),
                    "observacao": observacao.strip(),
                    "data_cadastro": datetime.now().strftime("%d/%m/%Y %H:%M")
                }
                
                if st.session_state.empresa_selecionada:  # Modo edição
                    # Atualiza a empresa existente
                    for i, emp in enumerate(st.session_state.empresas):
                        if emp["nome"] == st.session_state.empresa_selecionada:
                            st.session_state.empresas[i] = nova_empresa
                            break
                    st.success(f"Empresa '{nome_empresa}' atualizada com sucesso!")
                else:  # Nova empresa
                    st.session_state.empresas.append(nova_empresa)
                    st.success(f"Empresa '{nome_empresa}' cadastrada com sucesso!")
                
                # Finaliza o modo edição
                st.session_state.modo_edicao = False
                st.session_state.empresa_selecionada = nome_empresa
                st.rerun()

    if st.button("Cancelar"):
        st.session_state.modo_edicao = False
        st.rerun()

# ====================== DASHBOARD PRINCIPAL ======================
if st.session_state.empresa_selecionada and not st.session_state.modo_edicao:
    st.title(f"Dashboard - {st.session_state.empresa_selecionada}")
    
    # Aqui vai o resto do seu dashboard (gráficos, métricas, etc.)
    st.info("Dashboard da empresa carregado com sucesso!")
    
    # Exemplo: mostrar dados da empresa
    empresa_atual = next((emp for emp in st.session_state.empresas if emp["nome"] == st.session_state.empresa_selecionada), None)
    if empresa_atual:
        st.write(empresa_atual)

else:
    st.title("BPO Dashboard")
    st.warning("Selecione ou cadastre uma empresa no menu lateral para começar.")
