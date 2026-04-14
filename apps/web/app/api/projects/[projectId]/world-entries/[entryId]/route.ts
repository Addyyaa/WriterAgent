import { proxyBackend } from "@/server/bff/http";

export async function PATCH(req: Request, context: { params: Promise<{ projectId: string; entryId: string }> }) {
  const { projectId, entryId } = await context.params;
  const body = await req.json().catch(() => ({}));
  return proxyBackend({ path: `/v2/projects/${projectId}/world-entries/${entryId}`, method: "PATCH", body });
}

export async function DELETE(_: Request, context: { params: Promise<{ projectId: string; entryId: string }> }) {
  const { projectId, entryId } = await context.params;
  return proxyBackend({ path: `/v2/projects/${projectId}/world-entries/${entryId}`, method: "DELETE" });
}
