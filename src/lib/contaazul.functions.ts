import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import {
  getSupabase,
  obterToken,
  buscarSaldos,
  buscarV2,
  removerAcentos,
} from "./contaazul.server";

export const listarEmpresas = createServerFn({ method: "GET" }).handler(async () => {
  const sb = getSupabase();
  const { data, error } = await sb
    .from("tokens")
    .select("empresa,status,mensagem_erro")
    .order("empresa");
  if (error) throw new Error(error.message);
  return (data || []).map((r: any) => ({
    nome: r.empresa as string,
    status: (r.status || "ATIVO") as string,
    erro: r.mensagem_erro as string | null,
  }));
});

export type DashboardData = {
  labels: string[];
  receitas: number[];
  despesas: number[];
  saldo: number[];
  saldos_por_banco: { nome: string; saldo: number }[];
  resumo: { banco: number; total_rec: number; total_desp: number; saldo_final: number };
};

function dateRange(inicio: string, fim: string): string[] {
  const out: string[] = [];
  const d = new Date(inicio + "T00:00:00Z");
  const f = new Date(fim + "T00:00:00Z");
  while (d <= f) {
    out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return out;
}

export const getDashboard = createServerFn({ method: "GET" })
  .inputValidator((d) =>
    z
      .object({
        empresa: z.string(),
        data_inicio: z.string(),
        data_fim: z.string(),
      })
      .parse(d),
  )
  .handler(async ({ data }): Promise<DashboardData> => {
    const sb = getSupabase();
    let empresas: string[];
    if (data.empresa.toLowerCase() === "todas") {
      const { data: rows } = await sb.from("tokens").select("empresa");
      empresas = (rows || []).map((r: any) => r.empresa as string);
    } else {
      empresas = [data.empresa.trim()];
    }

    const resultados = await Promise.all(
      empresas.map(async (emp) => {
        const token = await obterToken(emp);
        if (!token) return { bancos: [], rec: [], desp: [] };
        const [bancos, rec, desp] = await Promise.all([
          buscarSaldos(emp, token),
          buscarV2(
            emp,
            "/v1/financeiro/eventos-financeiros/contas-a-receber/buscar",
            data.data_inicio,
            data.data_fim,
          ),
          buscarV2(
            emp,
            "/v1/financeiro/eventos-financeiros/contas-a-pagar/buscar",
            data.data_inicio,
            data.data_fim,
          ),
        ]);
        return { bancos, rec, desp };
      }),
    );

    const mapaBancos = new Map<string, { nome: string; saldo: number }>();
    for (const r of resultados) {
      for (const b of r.bancos) {
        const chave = removerAcentos(b.nome).toUpperCase();
        const ex = mapaBancos.get(chave);
        if (ex) ex.saldo += b.saldo;
        else
          mapaBancos.set(chave, {
            nome: chave.charAt(0) + chave.slice(1).toLowerCase(),
            saldo: b.saldo,
          });
      }
    }
    const saldos_por_banco = Array.from(mapaBancos.values()).map((v) => ({
      nome: v.nome,
      saldo: Math.round(v.saldo * 100) / 100,
    }));
    const totalBanco = saldos_por_banco.reduce((a, b) => a + b.saldo, 0);

    const datas = dateRange(data.data_inicio, data.data_fim);
    const recPorDia: Record<string, number> = {};
    const despPorDia: Record<string, number> = {};
    for (const r of resultados) {
      for (const i of r.rec) recPorDia[i.data] = (recPorDia[i.data] || 0) + i.valor;
      for (const i of r.desp) despPorDia[i.data] = (despPorDia[i.data] || 0) + i.valor;
    }

    const receitas: number[] = [];
    const despesas: number[] = [];
    const saldo: number[] = [];
    let acumulado = totalBanco;
    const labels: string[] = [];
    for (const d of datas) {
      const r = recPorDia[d] || 0;
      const p = despPorDia[d] || 0;
      receitas.push(r);
      despesas.push(p);
      acumulado += r - p;
      saldo.push(Math.round(acumulado * 100) / 100);
      const [y, m, day] = d.split("-");
      labels.push(`${day}/${m}`);
    }

    const total_rec = receitas.reduce((a, b) => a + b, 0);
    const total_desp = despesas.reduce((a, b) => a + b, 0);

    return {
      labels,
      receitas,
      despesas,
      saldo,
      saldos_por_banco,
      resumo: {
        banco: Math.round(totalBanco * 100) / 100,
        total_rec: Math.round(total_rec * 100) / 100,
        total_desp: Math.round(total_desp * 100) / 100,
        saldo_final: saldo.length ? saldo[saldo.length - 1] : Math.round(totalBanco * 100) / 100,
      },
    };
  });
