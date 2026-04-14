import { NextResponse } from "next/server";

import { parseAuthTokens } from "@/server/bff/auth-tokens";
import { resolveBackendBaseUrl } from "@/server/bff/config";
import { setAuthCookies } from "@/server/bff/cookies";

export async function POST(req: Request) {
  const payload = await req.json().catch(() => ({}));
  const backendBaseUrl = await resolveBackendBaseUrl();
  const res = await fetch(`${backendBaseUrl}/v2/auth/register`, {
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
    const detail = String(data?.detail || data?.error || "注册失败");
    return NextResponse.json({ detail }, { status: res.status });
  }

  const tokens = parseAuthTokens(data);
  if (!tokens) {
    return NextResponse.json({ detail: "注册成功但未返回有效 token" }, { status: 502 });
  }

  const out = NextResponse.json({ ok: true, user: data.user });
  setAuthCookies(out, tokens);
  return out;
}
