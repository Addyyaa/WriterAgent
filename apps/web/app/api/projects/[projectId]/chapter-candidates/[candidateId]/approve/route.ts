import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

function normalize(value: string): string {
  return String(value || "").trim();
}

export async function POST(_: Request, context: { params: Promise<{ projectId: string; candidateId: string }> }) {
  const { projectId, candidateId } = await context.params;
  const pid = normalize(projectId);
  const cid = normalize(candidateId);
  if (!pid || !cid) return NextResponse.json({ detail: "project_id/candidate_id 必填" }, { status: 400 });
  return proxyBackend({ path: `/v2/projects/${pid}/chapter-candidates/${cid}/approve`, method: "POST" });
}
