import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

function normalize(value: string): string {
  return String(value || "").trim();
}

export async function GET(req: Request, context: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await context.params;
  const pid = normalize(projectId);
  if (!pid) return NextResponse.json({ detail: "project_id 必填" }, { status: 400 });
  const url = new URL(req.url);
  const status = String(url.searchParams.get("status") || "").trim();
  const limit = String(url.searchParams.get("limit") || "").trim();
  const qs = new URLSearchParams();
  if (status) qs.set("status", status);
  if (limit) qs.set("limit", limit);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return proxyBackend({ path: `/v2/projects/${pid}/chapter-candidates${suffix}`, method: "GET" });
}
