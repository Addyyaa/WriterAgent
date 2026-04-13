import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

export async function POST(req: Request) {
  const payload = await req.json().catch(() => ({}));
  const projectId = String(payload.project_id || "").trim();
  if (!projectId) {
    return NextResponse.json({ detail: "project_id 必填" }, { status: 400 });
  }
  const body = { ...payload };
  delete body.project_id;
  return proxyBackend({
    path: `/v2/projects/${projectId}/writing/runs`,
    method: "POST",
    body
  });
}
