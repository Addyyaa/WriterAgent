import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

export async function POST(req: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  const normalized = String(projectId || "").trim();
  if (!normalized) {
    return NextResponse.json({ detail: "project_id 必填" }, { status: 400 });
  }
  const payload = await req.json().catch(() => ({}));
  return proxyBackend({
    path: `/v2/projects/${normalized}/ai-generate-asset`,
    method: "POST",
    body: payload
  });
}
