import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

function normalize(value: string): string {
  return String(value || "").trim();
}

export async function GET(_: Request, context: { params: Promise<{ projectId: string; chapterId: string }> }) {
  const { projectId, chapterId } = await context.params;
  const pid = normalize(projectId);
  const cid = normalize(chapterId);
  if (!pid || !cid) return NextResponse.json({ detail: "project_id/chapter_id 必填" }, { status: 400 });
  return proxyBackend({ path: `/v2/projects/${pid}/chapters/${cid}`, method: "GET" });
}

export async function PATCH(req: Request, context: { params: Promise<{ projectId: string; chapterId: string }> }) {
  const { projectId, chapterId } = await context.params;
  const pid = normalize(projectId);
  const cid = normalize(chapterId);
  if (!pid || !cid) return NextResponse.json({ detail: "project_id/chapter_id 必填" }, { status: 400 });
  const payload = await req.json().catch(() => ({}));
  return proxyBackend({ path: `/v2/projects/${pid}/chapters/${cid}`, method: "PATCH", body: payload });
}

export async function DELETE(_: Request, context: { params: Promise<{ projectId: string; chapterId: string }> }) {
  const { projectId, chapterId } = await context.params;
  const pid = normalize(projectId);
  const cid = normalize(chapterId);
  if (!pid || !cid) return NextResponse.json({ detail: "project_id/chapter_id 必填" }, { status: 400 });
  return proxyBackend({ path: `/v2/projects/${pid}/chapters/${cid}`, method: "DELETE" });
}
