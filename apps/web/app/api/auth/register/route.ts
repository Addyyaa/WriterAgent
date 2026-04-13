import { NextResponse } from "next/server";

import { getBackendBaseUrl } from "@/server/bff/config";
import { setAuthCookies } from "@/server/bff/cookies";

export async function POST(req: Request) {
  const payload = await req.json().catch(() => ({}));
  const res = await fetch(`${getBackendBaseUrl()}/v2/auth/register`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "User-Agent": req.headers.get("user-agent") || "writeragent-web"
    },
    body: JSON.stringify(payload),
    cache: "no-store"
  });

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    return NextResponse.json({ detail: data?.detail || "注册失败" }, { status: res.status });
  }

  const out = NextResponse.json({ ok: true, user: data.user });
  setAuthCookies(out, {
    access_token: String(data.access_token || ""),
    refresh_token: String(data.refresh_token || ""),
    expires_in: Number(data.expires_in || 3600)
  });
  return out;
}
