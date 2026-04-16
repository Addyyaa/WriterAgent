import { NextResponse } from "next/server";

import { proxyBackend } from "@/server/bff/http";

export async function PATCH(req: Request) {
  const body = await req.json().catch(() => ({}));
  if (!body || typeof body !== "object" || !("preferences" in body)) {
    return NextResponse.json({ detail: "preferences 必填" }, { status: 400 });
  }
  return proxyBackend({
    path: "/v2/auth/me/preferences",
    method: "PATCH",
    body,
  });
}
