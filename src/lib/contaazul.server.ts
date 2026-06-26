import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export function getSupabase(): SupabaseClient {
  const url = process.env.JRM_SUPABASE_URL;
  const key = process.env.JRM_SUPABASE_KEY;
  if (!url || !key) throw new Error("JRM_SUPABASE_URL/JRM_SUPABASE_KEY não configurados");
  return createClient(url, key, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export function removerAcentos(s: string): string {
  if (!s) return "";
  return s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
}

export function basicAuth(): string {
  const id = process.env.CONTA_AZUL_CLIENT_ID!;
  const secret = process.env.CONTA_AZUL_CLIENT_SECRET!;
  return Buffer.from(`${id}:${secret}`).toString("base64");
}

// ------------------- Logs em memória (ring buffer) -------------------
type LogEntry = { ts: number; nivel: "info" | "warn" | "error"; msg: string };
const LOGS: LogEntry[] = [];
const LOGS_MAX = 200;
export function log(nivel: LogEntry["nivel"], msg: string) {
  LOGS.push({ ts: Date.now(), nivel, msg });
  if (LOGS.length > LOGS_MAX) LOGS.splice(0, LOGS.length - LOGS_MAX);
  // espelha no console também
  const fn = nivel === "error" ? console.error : nivel === "warn" ? console.warn : console.log;
  fn(`[ca] ${msg}`);
}
export function getLogs(): LogEntry[] {
  return LOGS.slice().reverse();
}
export function limparLogs() {
  LOGS.length = 0;
}

// ------------------- Cache detalhe (id -> metodo) --------------------
const detalheCache = new Map<string, { metodo: string | null; exp: number }>();
const DETALHE_TTL_MS = 5 * 60 * 1000;

// ------------------- Retry helper ------------------------------------
async function fetchComRetry(
  url: string,
  init: RequestInit,
  tentativas = 3,
): Promise<Response> {
  let ultErro: any = null;
  for (let i = 0; i < tentativas; i++) {
    try {
      const r = await fetch(url, init);
      // 429 / 5xx: retry com backoff
      if (r.status === 429 || (r.status >= 500 && r.status < 600)) {
        if (i < tentativas - 1) {
          const espera = 300 * Math.pow(2, i);
          log("warn", `retry ${i + 1}/${tentativas} ${r.status} em ${url.slice(0, 120)} (espera ${espera}ms)`);
          await new Promise((res) => setTimeout(res, espera));
          continue;
        }
      }
      return r;
    } catch (e) {
      ultErro = e;
      if (i < tentativas - 1) {
        const espera = 300 * Math.pow(2, i);
        log("warn", `retry ${i + 1}/${tentativas} erro rede ${String(e).slice(0, 100)} (espera ${espera}ms)`);
        await new Promise((res) => setTimeout(res, espera));
        continue;
      }
    }
  }
  if (ultErro) throw ultErro;
  // não deveria chegar aqui
  return fetch(url, init);
}

// Deduplica refreshes concorrentes por empresa (evita invalidar refresh_token rotacionado)
const refreshEmAndamento = new Map<string, Promise<string | null>>();

async function executarRefresh(empresa: string): Promise<string | null> {
  const sb = getSupabase();
  const { data } = await sb
    .from("tokens")
    .select("refresh_token,access_token,updated_at")
    .eq("empresa", empresa)
    .limit(1);
  if (!data || !data.length) return null;
  const refresh = data[0].refresh_token;

  if (data[0].updated_at) {
    const idadeMs = Date.now() - new Date(data[0].updated_at).getTime();
    if (idadeMs < 30_000 && data[0].access_token) return data[0].access_token;
  }

  log("info", `renovando token: ${empresa}`);
  const res = await fetch("https://auth.contaazul.com/oauth2/token", {
    method: "POST",
    headers: {
      Authorization: `Basic ${basicAuth()}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: refresh }),
  });

  if (res.ok) {
    const j: any = await res.json();
    await sb
      .from("tokens")
      .update({
        access_token: j.access_token,
        refresh_token: j.refresh_token,
        status: "ATIVO",
        mensagem_erro: null,
        updated_at: new Date().toISOString(),
      })
      .eq("empresa", empresa);
    log("info", `token renovado: ${empresa}`);
    return j.access_token;
  }

  const txt = await res.text();
  const corpoLower = txt.toLowerCase();
  const ehInvalidGrant =
    res.status === 400 && (corpoLower.includes("invalid_grant") || corpoLower.includes("invalid_token"));
  if (ehInvalidGrant) {
    await sb
      .from("tokens")
      .update({
        status: "ERRO",
        mensagem_erro: `Token revogado: ${res.status} ${txt.slice(0, 200)}`,
        updated_at: new Date().toISOString(),
      })
      .eq("empresa", empresa);
    log("error", `token revogado: ${empresa} -> ${txt.slice(0, 200)}`);
  } else {
    log("warn", `refresh falhou (transitório): ${empresa} ${res.status}`);
  }
  return null;
}

export async function renovarToken(empresa: string): Promise<string | null> {
  const emAndamento = refreshEmAndamento.get(empresa);
  if (emAndamento) return emAndamento;
  const p = executarRefresh(empresa).finally(() => {
    refreshEmAndamento.delete(empresa);
  });
  refreshEmAndamento.set(empresa, p);
  return p;
}

export async function obterToken(empresa: string): Promise<string | null> {
  const sb = getSupabase();
  const { data } = await sb
    .from("tokens")
    .select("access_token,status")
    .eq("empresa", empresa)
    .limit(1);
  if (data && data.length) {
    if (data[0].status === "ERRO") return renovarToken(empresa);
    if (data[0].access_token) return data[0].access_token;
  }
  return renovarToken(empresa);
}

const BANCOS_PERMITIDOS = [
  "ITAU",
  "BRADESCO",
  "SICOOB",
  "SICREDI",
  "SANTANDER",
  "BANCO DO BRASIL",
  "NUBANK",
  "INTER",
];

export async function buscarSaldos(empresa: string, tokenInicial: string) {
  let token = tokenInicial;
  const lista: { nome: string; saldo: number }[] = [];
  let res = await fetchComRetry("https://api-v2.contaazul.com/v1/conta-financeira", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    const novo = await renovarToken(empresa);
    if (!novo) return lista;
    token = novo;
    res = await fetchComRetry("https://api-v2.contaazul.com/v1/conta-financeira", {
      headers: { Authorization: `Bearer ${token}` },
    });
  }
  if (!res.ok) {
    log("warn", `buscarSaldos ${empresa} status=${res.status}`);
    return lista;
  }
  const j: any = await res.json();
  const contas: any[] = Array.isArray(j) ? j : j.itens || [];

  const tarefas = contas
    .filter((c) => {
      const n = removerAcentos(c.nome || "").toUpperCase();
      return BANCOS_PERMITIDOS.some((b) => n.includes(b));
    })
    .map(async (c) => {
      const r = await fetchComRetry(
        `https://api-v2.contaazul.com/v1/conta-financeira/${c.id}/saldo-atual`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (r.ok) {
        const sj: any = await r.json();
        return { nome: c.nome as string, saldo: (sj.saldo_atual as number) || 0 };
      }
      return null;
    });

  const resps = await Promise.all(tarefas);
  for (const r of resps) if (r) lista.push(r);
  return lista;
}

function extrairMetodo(j: any): string | null {
  const candidatos: any[] = [
    j.forma_pagamento,
    j.metodo_pagamento,
    j.tipo_pagamento,
    j.meio_pagamento,
    j.forma_pagamento?.tipo,
    j.forma_pagamento?.nome,
    j.metodo_pagamento?.tipo,
    j.metodo_pagamento?.nome,
    j.parcelas?.[0]?.forma_pagamento,
    j.parcelas?.[0]?.forma_pagamento?.tipo,
    j.parcelas?.[0]?.forma_pagamento?.nome,
    j.parcelas?.[0]?.metodo_pagamento,
    j.parcelas?.[0]?.metodo_pagamento?.tipo,
    j.parcelas?.[0]?.metodo_pagamento?.nome,
    j.baixas?.[0]?.forma_pagamento,
    j.baixas?.[0]?.metodo_pagamento,
  ];
  for (const c of candidatos) {
    if (typeof c === "string" && c) return c;
    if (c && typeof c === "object") {
      const s = c.tipo || c.nome;
      if (typeof s === "string" && s) return s;
    }
  }
  return null;
}

async function buscarDetalheFormaPagamento(
  empresa: string,
  endpoint: string,
  id: string,
  tokenRef: { token: string },
): Promise<string | null> {
  const cacheKey = `${empresa}:${id}`;
  const cached = detalheCache.get(cacheKey);
  if (cached && cached.exp > Date.now()) return cached.metodo;

  const detalheUrl = `https://api-v2.contaazul.com${endpoint.replace(/\/buscar$/, "")}/${id}`;
  let res = await fetchComRetry(detalheUrl, { headers: { Authorization: `Bearer ${tokenRef.token}` } });
  if (res.status === 401) {
    const novo = await renovarToken(empresa);
    if (!novo) return null;
    tokenRef.token = novo;
    res = await fetchComRetry(detalheUrl, { headers: { Authorization: `Bearer ${tokenRef.token}` } });
  }
  if (!res.ok) {
    log("warn", `detalhe ${empresa} id=${id} status=${res.status}`);
    return null;
  }
  const j: any = await res.json();
  const metodo = extrairMetodo(j);
  detalheCache.set(cacheKey, { metodo, exp: Date.now() + DETALHE_TTL_MS });
  return metodo;
}

export async function buscarV2(
  empresa: string,
  endpoint: string,
  dataInicio: string,
  dataFim: string,
) {
  const tokenInicial = await obterToken(empresa);
  if (!tokenInicial) {
    log("warn", `buscarV2 sem token: ${empresa}`);
    return [] as { data: string; valor: number; metodo: string | null }[];
  }
  const tokenRef = { token: tokenInicial };

  const brutos: { id: string; data: string; valor: number }[] = [];
  let pagina = 1;
  let tentativasReauth = 0;

  while (true) {
    const params = new URLSearchParams({
      data_vencimento_de: dataInicio,
      data_vencimento_ate: dataFim,
      status: "EM_ABERTO",
      tamanho_pagina: "100",
      pagina: String(pagina),
    });
    const url = `https://api-v2.contaazul.com${endpoint}?${params}`;
    const res = await fetchComRetry(url, { headers: { Authorization: `Bearer ${tokenRef.token}` } });

    if (res.status === 401 && tentativasReauth < 1) {
      const novo = await renovarToken(empresa);
      if (!novo) break;
      tokenRef.token = novo;
      tentativasReauth++;
      continue;
    }
    if (!res.ok) {
      log("warn", `buscarV2 ${empresa} pg=${pagina} status=${res.status}`);
      break;
    }

    const j: any = await res.json();
    const itens: any[] = j.itens || [];
    if (!itens.length) break;

    for (const i of itens) {
      const dv = i.data_vencimento ? String(i.data_vencimento).slice(0, 10) : null;
      const aberto = (i.total || 0) - (i.pago || 0);
      if (dv && aberto > 0 && i.id) brutos.push({ id: String(i.id), data: dv, valor: aberto });
    }
    if (itens.length < 100) break;
    pagina++;
    tentativasReauth = 0;
  }

  const ehReceber = endpoint.includes("contas-a-receber");
  if (!ehReceber) {
    return brutos.map((b) => ({ data: b.data, valor: b.valor, metodo: null }));
  }

  const CONCORRENCIA = 8;
  const resultado: { data: string; valor: number; metodo: string | null }[] = new Array(brutos.length);
  let idx = 0;
  let boletos = 0;
  let comMetodo = 0;
  async function worker() {
    while (true) {
      const meu = idx++;
      if (meu >= brutos.length) return;
      const b = brutos[meu];
      const metodo = await buscarDetalheFormaPagamento(empresa, endpoint, b.id, tokenRef);
      if (metodo) comMetodo++;
      if (metodo && metodo.toUpperCase().includes("BOLETO")) boletos++;
      resultado[meu] = { data: b.data, valor: b.valor, metodo };
    }
  }
  await Promise.all(Array.from({ length: Math.min(CONCORRENCIA, brutos.length) }, worker));
  log(
    "info",
    `${empresa} a_receber=${brutos.length} com_metodo=${comMetodo} boletos=${boletos}`,
  );
  return resultado;
}

// Inspeciona o detalhe de N itens — usado pelo painel de debug pra ver o JSON cru.
export async function inspecionarPrimeirosRecebimentos(
  empresa: string,
  dataInicio: string,
  dataFim: string,
  limite = 3,
) {
  const token = await obterToken(empresa);
  if (!token) return { erro: "sem token" };
  const tokenRef = { token };
  const params = new URLSearchParams({
    data_vencimento_de: dataInicio,
    data_vencimento_ate: dataFim,
    status: "EM_ABERTO",
    tamanho_pagina: "20",
    pagina: "1",
  });
  const endpoint = "/v1/financeiro/eventos-financeiros/contas-a-receber/buscar";
  const url = `https://api-v2.contaazul.com${endpoint}?${params}`;
  const res = await fetchComRetry(url, { headers: { Authorization: `Bearer ${tokenRef.token}` } });
  if (!res.ok) return { erro: `lista ${res.status}` };
  const j: any = await res.json();
  const itens: any[] = (j.itens || []).slice(0, limite);
  const detalhes = [] as any[];
  for (const i of itens) {
    const id = String(i.id);
    const dUrl = `https://api-v2.contaazul.com${endpoint.replace(/\/buscar$/, "")}/${id}`;
    const r = await fetchComRetry(dUrl, { headers: { Authorization: `Bearer ${tokenRef.token}` } });
    if (!r.ok) {
      detalhes.push({ id, erro: r.status });
      continue;
    }
    const dj: any = await r.json();
    detalhes.push({ id, metodo_extraido: extrairMetodo(dj), bruto: dj });
  }
  return { lista_amostra: j.itens?.[0] || null, detalhes };
}
