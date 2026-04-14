import { proxyBackend } from "@/server/bff/http";

export async function GET(_: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  return proxyBackend({ path: `/v2/projects/${projectId}/outlines/latest`, method: "GET" });
}
