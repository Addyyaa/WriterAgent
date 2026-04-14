import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

function normalizeProjectId(projectId: string): string {
  return String(projectId || "").trim();
}

export async function POST(req: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  const normalized = normalizeProjectId(projectId);
  if (!normalized) {
    return NextResponse.json({ detail: "project_id 必填" }, { status: 400 });
  }
  const payload = await req.json().catch(() => ({}));
  return proxyBackend({
    path: `/v2/projects/${normalized}/bootstrap`,
    method: "POST",
    body: payload
  });
}
