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

  // Se outro processo já renovou nos últimos 30s, reusa o access_token do banco
  if (data[0].updated_at) {
    const idadeMs = Date.now() - new Date(data[0].updated_at).getTime();
    if (idadeMs < 30_000 && data[0].access_token) return data[0].access_token;
  }

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
    return j.access_token;
  }

  const txt = await res.text();
  // Só marca ERRO se for invalid_grant (refresh realmente revogado).
  // Erros transitórios (5xx, rede) não devem invalidar a credencial.
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
  let res = await fetch("https://api-v2.contaazul.com/v1/conta-financeira", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    const novo = await renovarToken(empresa);
    if (!novo) return lista;
    token = novo;
    res = await fetch("https://api-v2.contaazul.com/v1/conta-financeira", {
      headers: { Authorization: `Bearer ${token}` },
    });
  }
  if (!res.ok) return lista;
  const j: any = await res.json();
  const contas: any[] = Array.isArray(j) ? j : j.itens || [];

  const tarefas = contas
    .filter((c) => {
      const n = removerAcentos(c.nome || "").toUpperCase();
      return BANCOS_PERMITIDOS.some((b) => n.includes(b));
    })
    .map(async (c) => {
      const r = await fetch(
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

export async function buscarV2(
  empresa: string,
  endpoint: string,
  dataInicio: string,
  dataFim: string,
) {
  let token = await obterToken(empresa);
  if (!token) return [] as { data: string; valor: number }[];

  const acumulado: { data: string; valor: number }[] = [];
  let pagina = 1;
  let tentativasReauth = 0;

  while (true) {
    const params = new URLSearchParams({
      data_vencimento_de: dataInicio,
      data_vencimento_ate: dataFim,
      status: "EM_ABERTO",
      tamanho_pagina: "100",
      pagina: String(pagina),
      fields: "data_vencimento,total,pago",
    });
    const url = `https://api-v2.contaazul.com${endpoint}?${params}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });

    if (res.status === 401 && tentativasReauth < 1) {
      const novo = await renovarToken(empresa);
      if (!novo) break;
      token = novo;
      tentativasReauth++;
      continue;
    }
    if (!res.ok) break;

    const j: any = await res.json();
    const itens: any[] = j.itens || [];
    if (!itens.length) break;

    for (const i of itens) {
      const dv = i.data_vencimento ? String(i.data_vencimento).slice(0, 10) : null;
      const aberto = (i.total || 0) - (i.pago || 0);
      if (dv && aberto > 0) acumulado.push({ data: dv, valor: aberto });
    }
    if (itens.length < 100) break;
    pagina++;
    tentativasReauth = 0;
  }
  return acumulado;
}
