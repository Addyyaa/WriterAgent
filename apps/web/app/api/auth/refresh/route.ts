import { NextResponse } from "next/server";

import { getBackendBaseUrl } from "@/server/bff/config";
import { clearAuthCookies, getRefreshTokenFromCookie, setAuthCookies } from "@/server/bff/cookies";

export async function POST() {
  const refreshToken = await getRefreshTokenFromCookie();
  if (!refreshToken) {
    return NextResponse.json({ detail: "缺少 refresh token" }, { status: 401 });
  }

  const res = await fetch(`${getBackendBaseUrl()}/v2/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store"
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const out = NextResponse.json({ detail: data?.detail || "刷新失败" }, { status: res.status });
    clearAuthCookies(out);
    return out;
  }

  const out = NextResponse.json({ ok: true, user: data.user });
  setAuthCookies(out, {
    access_token: String(data.access_token || ""),
    refresh_token: String(data.refresh_token || ""),
    expires_in: Number(data.expires_in || 3600)
  });
  return out;
}
