import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { useServerFn } from "@tanstack/react-start";
import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart,
  Bar,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  Moon,
  Sun,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Wallet,
  TrendingUp,
  TrendingDown,
  Sparkles,
  RefreshCw,
  AlertTriangle,
  ArrowUpRight,
  ArrowDownRight,
  Barcode,
} from "lucide-react";
import {
  listarEmpresas,
  getDashboard,
  getServerLogs,
  limparServerLogs,
  inspecionarRecebimentos,
} from "@/lib/contaazul.functions";
import { useQueryClient } from "@tanstack/react-query";
import { Terminal, Trash2, Search } from "lucide-react";
import logo from "@/assets/logo.png";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Fluxo de Caixa - JRM Gestão" },
      { name: "description", content: "Dashboard de fluxo de caixa multi-empresa integrado à Conta Azul." },
      { property: "og:title", content: "Fluxo de Caixa - JRM Gestão" },
      { property: "og:description", content: "Dashboard de fluxo de caixa multi-empresa integrado à Conta Azul." },
      { property: "og:type", content: "website" },
    ],
    links: [{ rel: "icon", type: "image/png", href: logo }],
  }),
  component: Dashboard,
});

const fmt = (v: number) =>
  (Number(v) || 0).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

const fmtCompact = (v: number) =>
  Number(v).toLocaleString("pt-BR", { notation: "compact", compactDisplay: "short" });

function todayLocalISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const tz = d.getTimezoneOffset();
  return new Date(d.getTime() - tz * 60000).toISOString().slice(0, 10);
}

function getLogoUrl(nome: string): string {
  const n = (nome || "").toUpperCase();
  if (n.includes("ITAU"))
    return "https://upload.wikimedia.org/wikipedia/commons/8/8a/Banco_Ita%C3%BA_logo.svg";
  if (n.includes("BRADESCO")) return "https://banco.bradesco/assets/common/img/favicon.ico";
  if (n.includes("SICOOB")) return "https://www.sicoob.com.br/favicon.ico";
  return "";
}

function Dashboard() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [empresa, setEmpresa] = useState("todas");
  const [intervalo, setIntervalo] = useState("7");
  const [dataInicio, setDataInicio] = useState(todayLocalISO(0));
  const [dataFim, setDataFim] = useState(todayLocalISO(7));

  useEffect(() => {
    const saved = localStorage.getItem("theme");
    if (saved === "light") setTheme("light");
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    if (intervalo === "personalizado") return;
    const dias = parseInt(intervalo);
    setDataInicio(todayLocalISO(0));
    setDataFim(todayLocalISO(dias));
  }, [intervalo]);

  const listarEmpresasFn = useServerFn(listarEmpresas);
  const getDashboardFn = useServerFn(getDashboard);
  const getServerLogsFn = useServerFn(getServerLogs);
  const limparServerLogsFn = useServerFn(limparServerLogs);
  const inspecionarRecebimentosFn = useServerFn(inspecionarRecebimentos);
  const queryClient = useQueryClient();

  const { data: empresas = [], refetch: refetchEmpresas } = useQuery({
    queryKey: ["empresas"],
    queryFn: () => listarEmpresasFn(),
    refetchInterval: 30_000,
  });

  const {
    data,
    isFetching,
    refetch,
    dataUpdatedAt,
    isError,
    error,
  } = useQuery({
    queryKey: ["dashboard", empresa, dataInicio, dataFim],
    queryFn: () => getDashboardFn({ data: { empresa, data_inicio: dataInicio, data_fim: dataFim } }),
    enabled: !!dataInicio && !!dataFim,
  });

  // Painel de logs
  const [logsAbertos, setLogsAbertos] = useState(false);
  const { data: logs = [], refetch: refetchLogs } = useQuery({
    queryKey: ["server-logs"],
    queryFn: () => getServerLogsFn(),
    enabled: logsAbertos,
    refetchInterval: logsAbertos ? 3000 : false,
  });
  const [inspecao, setInspecao] = useState<any>(null);
  const [inspecionando, setInspecionando] = useState(false);

  async function recarregarTudo() {
    await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    await Promise.all([refetch(), refetchEmpresas(), logsAbertos ? refetchLogs() : Promise.resolve()]);
  }

  async function inspecionarAgora() {
    setInspecionando(true);
    try {
      const r = await inspecionarRecebimentosFn({
        data: { empresa, data_inicio: dataInicio, data_fim: dataFim },
      });
      setInspecao(r);
    } finally {
      setInspecionando(false);
      refetchLogs();
    }
  }

  const bancosPermitidos = ["ITAU", "SICOOB", "BRADESCO"];
  const bancosFiltrados = useMemo(() => {
    const bancos = data?.saldos_por_banco || [];
    const vistos = new Set<string>();
    return bancos
      .filter((b) => {
        const nu = (b.nome || "").toUpperCase();
        const ok = bancosPermitidos.some((p) => nu.includes(p));
        if (!ok || vistos.has(nu) || Math.abs(b.saldo) < 0.01) return false;
        vistos.add(nu);
        return true;
      })
      .sort((a, b) => a.nome.localeCompare(b.nome));
  }, [data]);

  const saldoAtual = bancosFiltrados.reduce((acc, b) => acc + b.saldo, 0);
  const totalRec = data?.resumo.total_rec || 0;
  const totalRecBoleto = data?.resumo.total_rec_boleto || 0;
  const totalRecOutros = Math.max(0, totalRec - totalRecBoleto);
  const totalDesp = Math.abs(data?.resumo.total_desp || 0);
  const saldoPrevisto = saldoAtual + totalRec - totalDesp;
  const variacao = saldoAtual > 0 ? ((saldoPrevisto - saldoAtual) / saldoAtual) * 100 : 0;
  const positivo = saldoPrevisto >= saldoAtual;

  const chartData = useMemo(() => {
    if (!data) return [];
    return data.labels.map((l, i) => ({
      label: l,
      receitas: data.receitas[i],
      despesas: -Math.abs(data.despesas[i]),
      saldo: data.saldo[i],
    }));
  }, [data]);



  return (
    <div className="min-h-screen w-full bg-background text-foreground font-sans relative overflow-hidden">
      {/* Background ambient glow */}
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="absolute -top-40 -right-40 h-[500px] w-[500px] rounded-full bg-brand/20 blur-[120px]" />
        <div className="absolute top-1/2 -left-40 h-[400px] w-[400px] rounded-full bg-brand-2/15 blur-[120px]" />
      </div>

      {isFetching && (
        <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-background/60 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-3">
            <Loader2 className="h-10 w-10 animate-spin text-brand" />
            <span className="text-sm text-muted-foreground">Sincronizando...</span>
          </div>
        </div>
      )}

      {/* Sidebar */}
      <aside
        className={`fixed left-0 top-0 z-40 h-screen w-[280px] border-r border-border bg-sidebar/80 backdrop-blur-xl p-6 flex flex-col overflow-y-auto transition-transform duration-300 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-3 mb-8">
          <div className="relative">
            <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-brand to-brand-2 blur-md opacity-60" />
            <img src={logo} alt="JRM" className="relative h-10 w-10 rounded-xl" />
          </div>
          <div>
            <div className="font-display font-bold text-lg leading-none">JRM</div>
            <div className="text-xs text-muted-foreground">Gestão Financeira</div>
          </div>
        </div>

        <SectionLabel>Filtros</SectionLabel>

        <Label>Empresa</Label>
        <Select value={empresa} onChange={(e) => setEmpresa(e.target.value)}>
          <option value="todas">Todas as Empresas</option>
          {empresas.map((e) => (
            <option key={e.nome} value={e.nome}>
              {e.nome}
              {e.status === "ERRO" ? " ⚠" : ""}
            </option>
          ))}
        </Select>

        <Label>Intervalo de Projeção</Label>
        <Select value={intervalo} onChange={(e) => setIntervalo(e.target.value)}>
          <option value="0">Hoje</option>
          <option value="7">Próximos 7 dias</option>
          <option value="15">Próximos 15 dias</option>
          <option value="30">Próximos 30 dias</option>
          <option value="personalizado">Personalizado</option>
        </Select>

        {intervalo === "personalizado" && (
          <>
            <Label>Início</Label>
            <Input type="date" value={dataInicio} onChange={(e) => setDataInicio(e.target.value)} />
            <Label>Fim</Label>
            <Input type="date" value={dataFim} onChange={(e) => setDataFim(e.target.value)} />
          </>
        )}

        <button
          onClick={recarregarTudo}
          disabled={isFetching}
          className="mt-2 w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-brand to-brand-2 px-4 py-3 text-sm font-semibold text-white shadow-lg shadow-brand/30 hover:shadow-brand/50 transition-shadow disabled:opacity-60"
        >
          <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
          {isFetching ? "Sincronizando..." : "Recarregar"}
        </button>
        
        <SectionLabel className="mt-8">Bancos</SectionLabel>
        <div className="space-y-2">
          {bancosFiltrados.length === 0 ? (
            <div className="text-xs text-muted-foreground text-center py-4">
              {isFetching ? "Carregando..." : "Aguardando sincronização..."}
            </div>
          ) : (
            bancosFiltrados.map((b) => {
              const url = getLogoUrl(b.nome);
              return (
                <div
                  key={b.nome}
                  className="flex items-center justify-between rounded-xl border border-border/50 bg-card/50 p-3 hover:border-brand/30 transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="h-8 w-8 rounded-lg bg-white flex items-center justify-center overflow-hidden text-[10px] font-bold text-black shrink-0">
                      {url ? (
                        <img src={url} alt="" className="h-full w-full object-contain" />
                      ) : (
                        (b.nome || "?").charAt(0)
                      )}
                    </div>
                    <div className="text-sm font-medium truncate" title={b.nome}>
                      {b.nome}
                    </div>
                  </div>
                  <div
                    className={`text-sm font-semibold tabular-nums ${
                      b.saldo < 0 ? "text-destructive" : ""
                    }`}
                  >
                    {fmt(b.saldo)}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>

      {/* Sidebar toggle */}
      <button
        onClick={() => setSidebarOpen((o) => !o)}
        className={`fixed top-6 z-50 rounded-full border border-border bg-card/80 backdrop-blur p-2 text-foreground/70 hover:text-foreground hover:border-brand/40 transition-all ${
          sidebarOpen ? "left-[268px]" : "left-4"
        }`}
      >
        {sidebarOpen ? <ChevronLeft className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {/* Main */}
      <main
        className={`min-h-screen transition-[margin] duration-300 ${
          sidebarOpen ? "ml-[280px]" : "ml-0"
        }`}
      >
        <div className="mx-auto max-w-[1400px] p-6 lg:p-10">
          {/* Header */}
          <div className="flex items-start justify-between mb-8 gap-4 flex-wrap">
            <div className="pl-12 lg:pl-0">
              <div className="flex items-center gap-2 text-xs uppercase tracking-widest text-muted-foreground mb-2">
                <Sparkles className="h-3 w-3 text-brand" />
                Visão Geral
              </div>
              <h1 className="font-display text-3xl lg:text-4xl font-bold tracking-tight">
                Fluxo de Caixa
              </h1>
              <p className="text-sm text-muted-foreground mt-1">
                Projeção de {dataInicio.split("-").reverse().join("/")} até{" "}
                {dataFim.split("-").reverse().join("/")}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={recarregarTudo}
                disabled={isFetching}
                className="flex items-center gap-2 rounded-full border border-border bg-card/60 backdrop-blur px-4 py-2 text-xs font-semibold hover:border-brand/40 transition-colors disabled:opacity-60"
                title="Recarregar dados"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? "animate-spin" : ""}`} />
                Recarregar
              </button>
              <button
                onClick={() => setLogsAbertos((v) => !v)}
                className={`flex items-center gap-2 rounded-full border px-4 py-2 text-xs font-semibold transition-colors ${
                  logsAbertos
                    ? "border-brand/50 bg-brand/10 text-brand"
                    : "border-border bg-card/60 backdrop-blur hover:border-brand/40"
                }`}
                title="Painel de logs"
              >
                <Terminal className="h-3.5 w-3.5" />
                Logs
              </button>
              <button
                onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
                className="rounded-full border border-border bg-card/60 backdrop-blur p-2.5 hover:border-brand/40 transition-colors"
                title="Alternar tema"
              >
                {theme === "light" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </button>
            </div>
          </div>
         
          {/* KPI cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 mb-8">
            <KpiCard
              label="Saldo Atual"
              valor={saldoAtual}
              icon={<Wallet className="h-5 w-5" />}
              gradient="from-brand/30 via-brand/10 to-transparent"
              accent="text-brand"
            />
            <KpiCard
              label="Entradas Previstas"
              valor={totalRec}
              icon={<TrendingUp className="h-5 w-5" />}
              gradient="from-success/30 via-success/10 to-transparent"
              accent="text-success"
              badge={<ArrowUpRight className="h-3 w-3" />}
            />
            <KpiCard
              label="Saídas Previstas"
              valor={-totalDesp}
              icon={<TrendingDown className="h-5 w-5" />}
              gradient="from-destructive/30 via-destructive/10 to-transparent"
              accent="text-destructive"
              badge={<ArrowDownRight className="h-3 w-3" />}
            />
            <KpiCard
              label="Saldo Previsto"
              valor={saldoPrevisto}
              icon={<Sparkles className="h-5 w-5" />}
              gradient={
                positivo
                  ? "from-brand-2/30 via-brand-2/10 to-transparent"
                  : "from-destructive/30 via-destructive/10 to-transparent"
              }
              accent={positivo ? "text-brand-2" : "text-destructive"}
              variation={Number.isFinite(variacao) ? variacao : null}
            />
          </div>

          {/* Breakdown de recebimentos por meio de pagamento */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-8">
            <KpiCard
              label="A Receber via Boleto"
              valor={totalRecBoleto}
              icon={<Barcode className="h-5 w-5" />}
              gradient="from-brand-2/30 via-brand-2/10 to-transparent"
              accent="text-brand-2"
              sub={
                totalRec > 0
                  ? `${((totalRecBoleto / totalRec) * 100).toFixed(1)}% do total a receber`
                  : "Sem recebimentos no período"
              }
            />
            <KpiCard
              label="A Receber - Outros Meios"
              valor={totalRecOutros}
              icon={<TrendingUp className="h-5 w-5" />}
              gradient="from-success/30 via-success/10 to-transparent"
              accent="text-success"
              sub="PIX, cartão, dinheiro, etc."
            />
          </div>





          {/* Chart */}
          <div className="relative rounded-2xl border border-border bg-card/60 backdrop-blur-xl p-6 shadow-xl overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-br from-brand/5 via-transparent to-brand-2/5 pointer-events-none" />
            <div className="relative">
              <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
                <div>
                  <h2 className="font-display text-lg font-semibold">Projeção Diária</h2>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Receitas, despesas e saldo acumulado
                  </p>
                </div>
                <div className="flex items-center gap-4 text-xs">
                  <LegendDot color="var(--color-success)" label="Receitas" />
                  <LegendDot color="var(--color-destructive)" label="Despesas" />
                  <LegendDot color="var(--color-brand)" label="Saldo" line />
                </div>
              </div>

              <div className="h-[420px]">
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} stackOffset="sign" margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                    <defs>
                      <linearGradient id="gradSaldo" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--color-brand)" stopOpacity={0.4} />
                        <stop offset="100%" stopColor="var(--color-brand)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="var(--color-border)" vertical={false} strokeDasharray="3 3" />
                    <XAxis
                      dataKey="label"
                      tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tickFormatter={fmtCompact}
                      tick={{ fill: "var(--color-muted-foreground)", fontSize: 11 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "var(--color-muted)", opacity: 0.3 }}
                      contentStyle={{
                        background: "var(--color-card)",
                        border: "1px solid var(--color-border)",
                        borderRadius: 12,
                        boxShadow: "0 10px 40px rgba(0,0,0,0.3)",
                        color: "var(--color-foreground)",
                      }}
                      labelStyle={{ color: "var(--color-muted-foreground)", fontSize: 12, marginBottom: 4 }}
                      formatter={(v: number, name: string) => [fmt(v as number), name]}
                    />
                    <Bar dataKey="receitas" name="Receitas" stackId="ops" fill="var(--color-success)" radius={[6, 6, 0, 0]} maxBarSize={32} />
                    <Bar dataKey="despesas" name="Despesas" stackId="ops" fill="var(--color-destructive)" radius={[6, 6, 0, 0]} maxBarSize={32} />
                    <Area
                      type="monotone"
                      dataKey="saldo"
                      name="Saldo"
                      stroke="var(--color-brand)"
                      strokeWidth={2.5}
                      fill="url(#gradSaldo)"
                      dot={{ r: 3, fill: "var(--color-brand)", strokeWidth: 0 }}
                      activeDot={{ r: 5 }}
                    />
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          {/* Alerta de empresas com erro */}
          {empresas.some((e) => e.status === "ERRO") && (
            <div className="mt-6 flex items-start gap-3 rounded-xl border border-warning/30 bg-warning/10 p-4">
              <AlertTriangle className="h-5 w-5 text-warning shrink-0 mt-0.5" />
              <div className="text-sm">
                <div className="font-semibold mb-1">Algumas empresas precisam reautenticar</div>
                <div className="text-muted-foreground">
                  {empresas.filter((e) => e.status === "ERRO").map((e) => e.nome).join(", ")}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* Painel de Logs (drawer inferior) */}
      {logsAbertos && (
        <div className="fixed bottom-0 left-0 right-0 z-40 max-h-[60vh] border-t border-border bg-card/95 backdrop-blur-xl shadow-2xl flex flex-col">
          <div className="flex items-center justify-between border-b border-border px-5 py-3">
            <div className="flex items-center gap-2">
              <Terminal className="h-4 w-4 text-brand" />
              <span className="text-sm font-semibold">Logs do servidor</span>
              <span className="text-xs text-muted-foreground">({logs.length})</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={inspecionarAgora}
                disabled={inspecionando || empresa === "todas"}
                className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:border-brand/40 disabled:opacity-50"
                title={empresa === "todas" ? "Selecione uma empresa específica" : "Buscar detalhe cru de 3 recebimentos"}
              >
                <Search className="h-3 w-3" />
                {inspecionando ? "Inspecionando..." : "Inspecionar API"}
              </button>
              <button
                onClick={async () => {
                  await limparServerLogsFn();
                  refetchLogs();
                  setInspecao(null);
                }}
                className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs hover:border-destructive/40 hover:text-destructive"
              >
                <Trash2 className="h-3 w-3" />
                Limpar
              </button>
              <button
                onClick={() => setLogsAbertos(false)}
                className="rounded-lg border border-border px-3 py-1.5 text-xs hover:border-brand/40"
              >
                Fechar
              </button>
            </div>
          </div>
          <div className="overflow-auto p-4 font-mono text-[11px] leading-relaxed">
            {logs.length === 0 && !inspecao && (
              <div className="text-muted-foreground text-center py-6">Sem logs ainda. Clique em Recarregar.</div>
            )}
            {logs.map((l, i) => (
              <div
                key={i}
                className={`flex gap-3 py-0.5 ${
                  l.nivel === "error" ? "text-destructive" : l.nivel === "warn" ? "text-warning" : "text-foreground/80"
                }`}
              >
                <span className="text-muted-foreground shrink-0">
                  {new Date(l.ts).toLocaleTimeString("pt-BR")}
                </span>
                <span className="uppercase shrink-0 w-12 opacity-70">{l.nivel}</span>
                <span className="whitespace-pre-wrap break-all">{l.msg}</span>
              </div>
            ))}
            {inspecao && (
              <details open className="mt-4 rounded-lg border border-brand/30 bg-brand/5 p-3">
                <summary className="cursor-pointer text-xs font-semibold text-brand">
                  Inspeção da API (JSON cru — procure por forma/metodo de pagamento)
                </summary>
                <pre className="mt-2 overflow-auto max-h-[40vh] text-[10px]">
                  {JSON.stringify(inspecao, null, 2)}
                </pre>
              </details>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function tempoRelativo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  const d = Math.floor(h / 24);
  return `${d}d`;
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-xs font-medium text-muted-foreground mb-1.5 mt-3">{children}</label>;
}

function SectionLabel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <h3 className={`text-[10px] font-bold uppercase tracking-[0.15em] text-muted-foreground mb-3 ${className}`}>
      {children}
    </h3>
  );
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="w-full rounded-xl border border-border bg-background/50 px-3 py-2.5 text-sm focus:outline-none focus:border-brand/50 focus:ring-2 focus:ring-brand/20 transition-all mb-1"
    />
  );
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full rounded-xl border border-border bg-background/50 px-3 py-2.5 text-sm focus:outline-none focus:border-brand/50 focus:ring-2 focus:ring-brand/20 transition-all mb-1"
    />
  );
}

function LegendDot({ color, label, line }: { color: string; label: string; line?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 text-muted-foreground">
      {line ? (
        <span className="h-[2px] w-4 rounded-full" style={{ background: color }} />
      ) : (
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color }} />
      )}
      {label}
    </div>
  );
}

function KpiCard({
  label,
  valor,
  icon,
  gradient,
  accent,
  badge,
  variation,
  sub,
}: {
  label: string;
  valor: number;
  icon: React.ReactNode;
  gradient: string;
  accent: string;
  badge?: React.ReactNode;
  variation?: number | null;
  sub?: string;
}) {
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-border bg-card/60 backdrop-blur-xl p-5 shadow-lg hover:border-brand/30 hover:-translate-y-0.5 transition-all">
      <div className={`absolute -top-12 -right-12 h-32 w-32 rounded-full bg-gradient-to-br ${gradient} blur-2xl opacity-80 group-hover:opacity-100 transition-opacity`} />
      <div className="relative">
        <div className="flex items-center justify-between mb-4">
          <div className={`flex h-10 w-10 items-center justify-center rounded-xl bg-background/60 border border-border ${accent}`}>
            {icon}
          </div>
          {badge && (
            <div className={`flex h-6 w-6 items-center justify-center rounded-full bg-background/60 border border-border ${accent}`}>
              {badge}
            </div>
          )}
          {variation !== null && variation !== undefined && (
            <div
              className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold ${
                variation >= 0
                  ? "border-success/30 bg-success/10 text-success"
                  : "border-destructive/30 bg-destructive/10 text-destructive"
              }`}
            >
              {variation >= 0 ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
              {Math.abs(variation).toFixed(1)}%
            </div>
          )}
        </div>
        <div className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
          {label}
        </div>
        <div className={`font-display text-2xl lg:text-[1.7rem] font-bold tabular-nums tracking-tight ${accent}`}>
          {fmt(valor)}
        </div>
        {sub && (
          <div className="mt-1.5 text-[11px] text-muted-foreground">{sub}</div>
        )}
      </div>
    </div>
  );
}

