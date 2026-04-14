import { proxyBackend } from "@/server/bff/http";

export async function GET(_: Request, context: { params: Promise<{ projectId: string; characterId: string }> }) {
  const { projectId, characterId } = await context.params;
  return proxyBackend({ path: `/v2/projects/${projectId}/characters/${characterId}`, method: "GET" });
}

export async function PATCH(req: Request, context: { params: Promise<{ projectId: string; characterId: string }> }) {
  const { projectId, characterId } = await context.params;
  const body = await req.json().catch(() => ({}));
  return proxyBackend({ path: `/v2/projects/${projectId}/characters/${characterId}`, method: "PATCH", body });
}

export async function DELETE(_: Request, context: { params: Promise<{ projectId: string; characterId: string }> }) {
  const { projectId, characterId } = await context.params;
  return proxyBackend({ path: `/v2/projects/${projectId}/characters/${characterId}`, method: "DELETE" });
}
