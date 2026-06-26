import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/api/callback")({
  server: {
    handlers: {
      GET: async ({ request }) => {
        const url = new URL(request.url);
        const code = url.searchParams.get("code");
        if (!code) return new Response("Código não fornecido.", { status: 400 });

        const { getSupabase, basicAuth } = await import("@/lib/contaazul.server");

        const redirect_uri = `${url.origin}/api/callback`;
        const tokenRes = await fetch("https://auth.contaazul.com/oauth2/token", {
          method: "POST",
          headers: {
            Authorization: `Basic ${basicAuth()}`,
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: new URLSearchParams({ grant_type: "authorization_code", redirect_uri, code }),
        });

        if (!tokenRes.ok) {
          const detalhe = await tokenRes.text();
          return Response.json({ status: "erro", detalhe }, { status: 400 });
        }
        const dados: any = await tokenRes.json();
        const access = dados.access_token as string;
        const refresh = dados.refresh_token as string;

        let nome = "NOVA_EMPRESA";
        const info = await fetch("https://api-v2.contaazul.com/v1/info", {
          headers: { Authorization: `Bearer ${access}` },
        });
        if (info.ok) {
          const ij: any = await info.json();
          if (ij?.name) nome = String(ij.name).toUpperCase();
        }

        const sb = getSupabase();
        await sb.from("tokens").upsert({
          empresa: nome,
          access_token: access,
          refresh_token: refresh,
          status: "ATIVO",
          mensagem_erro: null,
          updated_at: new Date().toISOString(),
        });

        return Response.json({ status: "sucesso", empresa: nome });
      },
    },
  },
});
