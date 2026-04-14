import { proxyBackend } from "@/server/bff/http";

export async function POST(_: Request, context: { params: Promise<{ runId: string }> }) {
  const { runId } = await context.params;
  const normalized = String(runId || "").trim();
  return proxyBackend({ path: `/v2/writing/runs/${normalized}/retry`, method: "POST", body: {} });
}
