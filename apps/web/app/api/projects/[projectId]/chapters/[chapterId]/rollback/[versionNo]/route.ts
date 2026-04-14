import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

function normalize(value: string): string {
  return String(value || "").trim();
}

export async function POST(_: Request, context: { params: Promise<{ projectId: string; chapterId: string; versionNo: string }> }) {
  const { projectId, chapterId, versionNo } = await context.params;
  const pid = normalize(projectId);
  const cid = normalize(chapterId);
  const ver = normalize(versionNo);
  if (!pid || !cid || !ver) {
    return NextResponse.json({ detail: "project_id/chapter_id/version_no 必填" }, { status: 400 });
  }
  return proxyBackend({ path: `/v2/projects/${pid}/chapters/${cid}/rollback/${ver}`, method: "POST" });
}
