# --- 1. CONFIGURAÇÕES INICIAIS ---
st.set_page_config(page_title="BPO Dashboard", layout="wide")

if 'theme' not in st.session_state:
    st.session_state.theme = 'dark'

IS_DARK    = st.session_state.theme == 'dark'
BG_COLOR   = "#0e1117"  if IS_DARK else "#ffffff"
TEXT_COLOR = "#ffffff"   if IS_DARK else "#31333F"
INPUT_BG   = "#262730"   if IS_DARK else "#f0f2f6"
BORDER     = "#555"      if IS_DARK else "#ccc"
PLOTLY_TPL = "plotly_dark" if IS_DARK else "plotly_white"

# --- 2. CSS + CALENDÁRIO PT-BR ---
st.markdown(f"""
<style>
    header {{visibility: hidden;}}
    .stApp {{ background-color: {BG_COLOR}; color: {TEXT_COLOR}; }}

    /* ── SIDEBAR COMPLETO ── */
    section[data-testid="stSidebar"] {{
        background-color: {"#16181f" if IS_DARK else "#f8f9fb"} !important;
    }}
    section[data-testid="stSidebar"] * {{
        color: {TEXT_COLOR} !important;
    }}

    /* ── DATE INPUT: remove ponta branca ── */
    div[data-testid="stDateInput"] {{
        background: transparent !important;
    }}
    div[data-testid="stDateInput"] > div,
    div[data-testid="stDateInput"] > div > div {{
        background-color: {INPUT_BG} !important;
        border-color: {BORDER} !important;
        border-radius: 8px !important;
    }}
    div[data-testid="stDateInput"] input {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
        border-radius: 8px !important;
        caret-color: {TEXT_COLOR} !important;
    }}

    /* ── CALENDÁRIO POPOVER (tema escuro) ── */
    div[data-baseweb="popover"],
    div[data-baseweb="popover"] > div {{
        background-color: {"#1e2029" if IS_DARK else "#ffffff"} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 10px !important;
    }}
    div[data-baseweb="calendar"],
    div[data-baseweb="calendar"] * {{
        background-color: {"#1e2029" if IS_DARK else "#ffffff"} !important;
        color: {TEXT_COLOR} !important;
    }}
    /* Dia selecionado */
    div[data-baseweb="calendar"] [aria-selected="true"] div {{
        background-color: #e05c2f !important;
        border-radius: 50% !important;
        color: #fff !important;
    }}
    /* Hover nos dias */
    div[data-baseweb="calendar"] [role="button"]:hover div {{
        background-color: {"#333" if IS_DARK else "#eee"} !important;
        border-radius: 50% !important;
    }}
    /* Setas de navegação do calendário */
    div[data-baseweb="calendar"] button {{
        background: transparent !important;
        color: {TEXT_COLOR} !important;
    }}
    /* Dropdowns de Mês/Ano dentro do calendário */
    div[data-baseweb="calendar"] select {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
        border: 1px solid {BORDER} !important;
    }}

    /* ── SELECT / DROPDOWN ── */
    div[data-baseweb="select"] > div {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
        border-color: {BORDER} !important;
    }}
    li[role="option"] {{
        background-color: {INPUT_BG} !important;
        color: {TEXT_COLOR} !important;
    }}
    li[role="option"]:hover {{
        background-color: {"#333" if IS_DARK else "#e0e0e0"} !important;
    }}

    /* ── BOTÃO DE TEMA ── */
    #theme-btn button {{
        background-color: {"#262730" if IS_DARK else "#f0f2f6"} !important;
        color: {TEXT_COLOR} !important;
        border: 1px solid {BORDER} !important;
        border-radius: 8px !important;
        padding: 0.3rem 0.7rem !important;
        font-size: 18px !important;
        cursor: pointer;
        transition: background 0.2s;
    }}
    #theme-btn button:hover {{
        background-color: {"#333" if IS_DARK else "#ddd"} !important;
    }}

    /* ── MÉTRICAS ── */
    [data-testid="stMetricValue"],
    [data-testid="stMetricLabel"] {{ color: {TEXT_COLOR} !important; }}
</style>

<script>
// Tradução PT-BR do calendário via MutationObserver
const MESES = ['Janeiro','Fevereiro','Março','Abril','Maio','Junho',
               'Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];
const DIAS  = ['Dom','Seg','Ter','Qua','Qui','Sex','Sáb'];
const EN_PT = {{'January':'Janeiro','February':'Fevereiro','March':'Março',
                'April':'Abril','May':'Maio','June':'Junho','July':'Julho',
                'August':'Agosto','September':'Setembro','October':'Outubro',
                'November':'Novembro','December':'Dezembro',
                'Su':'Dom','Mo':'Seg','Tu':'Ter','We':'Qua',
                'Th':'Qui','Fr':'Sex','Sa':'Sáb',
                'Previous month':'Mês anterior','Next month':'Próximo mês'}};

function traduzir(el) {{
    if (!el) return;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {{
        const t = node.nodeValue.trim();
        if (EN_PT[t]) node.nodeValue = node.nodeValue.replace(t, EN_PT[t]);
    }}
    el.querySelectorAll('[aria-label]').forEach(e => {{
        const lbl = e.getAttribute('aria-label');
        if (EN_PT[lbl]) e.setAttribute('aria-label', EN_PT[lbl]);
    }});
}}

const obs = new MutationObserver(muts => {{
    muts.forEach(m => {{
        m.addedNodes.forEach(n => {{
            if (n.nodeType === 1) {{
                const cal = n.querySelector ? n.querySelector('[data-baseweb="calendar"]') : null;
                if (cal) traduzir(cal);
                if (n.getAttribute && n.getAttribute('data-baseweb') === 'calendar') traduzir(n);
            }}
        }});
    }});
}});
obs.observe(document.body, {{ childList: true, subtree: true }});
</script>
""", unsafe_allow_html=True)

# Título + Botão Tema (lado a lado)
col_titulo, col_tema = st.columns([11, 1])
with col_titulo:
    st.title("📊 Fluxo de Caixa BPO")
with col_tema:
    st.markdown('<div id="theme-btn">', unsafe_allow_html=True)
    if st.button("🌓", key="toggle_theme", help="Alternar tema claro/escuro"):
        st.session_state.theme = 'light' if IS_DARK else 'dark'
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)
