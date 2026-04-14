import { proxyBackend } from "@/server/bff/http";

export async function GET(_: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  return proxyBackend({ path: `/v2/projects/${projectId}/world-entries`, method: "GET" });
}

export async function POST(req: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  const body = await req.json().catch(() => ({}));
  return proxyBackend({ path: `/v2/projects/${projectId}/world-entries`, method: "POST", body });
}
