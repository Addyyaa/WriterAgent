import { proxyBackend } from "@/server/bff/http";

export async function GET(req: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  const url = new URL(req.url);
  const days = url.searchParams.get("days");
  const q = days ? `?days=${encodeURIComponent(days)}` : "";
  return proxyBackend({
    path: `/v2/projects/${projectId}/retrieval-eval/daily${q}`,
    method: "GET",
  });
}
