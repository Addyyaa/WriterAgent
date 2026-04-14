import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

function normalizeProjectId(projectId: string): string {
  return String(projectId || "").trim();
}

export async function GET(req: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  const normalized = normalizeProjectId(projectId);
  if (!normalized) {
    return NextResponse.json({ detail: "project_id 必填" }, { status: 400 });
  }
  const url = new URL(req.url);
  const includeContent = String(url.searchParams.get("include_content") || "").trim();
  const suffix = includeContent ? `?include_content=${encodeURIComponent(includeContent)}` : "";
  return proxyBackend({ path: `/v2/projects/${normalized}/chapters${suffix}`, method: "GET" });
}

export async function POST(req: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  const normalized = normalizeProjectId(projectId);
  if (!normalized) {
    return NextResponse.json({ detail: "project_id 必填" }, { status: 400 });
  }
  const payload = await req.json().catch(() => ({}));
  return proxyBackend({ path: `/v2/projects/${normalized}/chapters`, method: "POST", body: payload });
}
