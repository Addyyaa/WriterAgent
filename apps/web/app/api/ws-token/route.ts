import { NextResponse } from "next/server";

import { resolveBackendBaseUrl } from "@/server/bff/config";
import { clearAuthCookies, getAccessTokenFromCookie, getRefreshTokenFromCookie, setAuthCookies } from "@/server/bff/cookies";
import { refreshAuthFromCookiesSingleFlight } from "@/server/bff/refresh-single-flight";

async function canAccessMe(backendBaseUrl: string, token: string): Promise<boolean> {
  const res = await fetch(`${backendBaseUrl}/v2/auth/me`, {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store"
  }).catch(() => null);
  return Boolean(res && res.ok);
}

export async function GET() {
  const backendBaseUrl = await resolveBackendBaseUrl();
  const accessToken = await getAccessTokenFromCookie();
  const refreshToken = await getRefreshTokenFromCookie();

  if (accessToken && (await canAccessMe(backendBaseUrl, accessToken))) {
    return NextResponse.json({
      token: accessToken,
      ws_url: backendBaseUrl
    });
  }

  if (!refreshToken) {
    const out = NextResponse.json({ detail: "未登录或登录态已过期" }, { status: 401 });
    clearAuthCookies(out);
    return out;
  }

  const refreshedResult = await refreshAuthFromCookiesSingleFlight(backendBaseUrl);
  if (!refreshedResult.ok) {
    const out = NextResponse.json({ detail: refreshedResult.detail }, { status: 401 });
    clearAuthCookies(out);
    return out;
  }

  const refreshed = refreshedResult.tokens;
  const out = NextResponse.json({
    token: refreshed.access_token,
    ws_url: backendBaseUrl
  });
  setAuthCookies(out, refreshed);
  return out;
}
