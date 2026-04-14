import { proxyBackend } from "@/server/bff/http";

export async function GET(req: Request, context: { params: Promise<{ projectId: string; characterId: string }> }) {
  const { projectId, characterId } = await context.params;
  const url = new URL(req.url);
  const chapterNo = url.searchParams.get("chapter_no");
  const q = chapterNo ? `?chapter_no=${encodeURIComponent(chapterNo)}` : "";
  return proxyBackend({
    path: `/v2/projects/${projectId}/characters/${characterId}/chapter-assets${q}`,
    method: "GET",
  });
}

export async function PUT(req: Request, context: { params: Promise<{ projectId: string; characterId: string }> }) {
  const { projectId, characterId } = await context.params;
  const body = await req.json().catch(() => ({}));
  return proxyBackend({
    path: `/v2/projects/${projectId}/characters/${characterId}/chapter-assets`,
    method: "PUT",
    body,
  });
}
