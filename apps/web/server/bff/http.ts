import { NextResponse } from "next/server";

import { parseAuthTokens } from "@/server/bff/auth-tokens";
import { resolveBackendBaseUrl } from "@/server/bff/config";
import {
  clearAuthCookies,
  getAccessTokenFromCookie,
  getRefreshTokenFromCookie,
  setAuthCookies
} from "@/server/bff/cookies";
import { refreshAuthFromCookiesSingleFlight } from "@/server/bff/refresh-single-flight";

type ProxyOptions = {
  path: string;
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  passThroughHeaders?: Record<string, string>;
};

async function refreshAccessToken(
  backendBaseUrl: string,
  refreshToken: string
): Promise<{ ok: true; tokens: { access_token: string; refresh_token: string; expires_in?: number } } | { ok: false; detail: string }> {
  const refreshRes = await fetch(`${backendBaseUrl}/v2/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store"
  });
  const refreshBody = await refreshRes.json().catch(() => ({}));
  if (!refreshRes.ok) {
    return { ok: false, detail: String(refreshBody?.detail || "登录态已过期") };
  }
  const refreshed = parseAuthTokens(refreshBody);
  if (!refreshed) {
    return { ok: false, detail: "刷新返回数据不完整" };
  }
  return { ok: true, tokens: refreshed };
}

export async function proxyBackend(options: ProxyOptions): Promise<NextResponse> {
  let token = await getAccessTokenFromCookie();
  const refreshToken = await getRefreshTokenFromCookie();
  const backendBaseUrl = await resolveBackendBaseUrl();
  let refreshedTokens: { access_token: string; refresh_token: string; expires_in?: number } | null = null;

  if (!token) {
    if (!refreshToken) return NextResponse.json({ detail: "未登录" }, { status: 401 });
    const refreshed = await refreshAuthFromCookiesSingleFlight(backendBaseUrl);
    if (!refreshed.ok) {
      const out = NextResponse.json({ detail: refreshed.detail }, { status: 401 });
      clearAuthCookies(out);
      return out;
    }
    refreshedTokens = refreshed.tokens;
    token = refreshed.tokens.access_token;
  }

  const execute = (accessToken: string) =>
    fetch(`${backendBaseUrl}${options.path}`, {
      method: options.method || "GET",
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.passThroughHeaders || {})
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store"
    });

  const toResponse = async (res: Response) => {
    const text = await res.text();
    const contentType = res.headers.get("content-type") || "application/json";
    return new NextResponse(text, {
      status: res.status,
      headers: { "content-type": contentType }
    });
  };

  let upstream = await execute(token);
  if (upstream.status !== 401) {
    const out = await toResponse(upstream);
    if (refreshedTokens) setAuthCookies(out, refreshedTokens);
    return out;
  }

  const rtForRetry = refreshedTokens?.refresh_token ?? refreshToken;
  if (!rtForRetry) return toResponse(upstream);
  const refreshed = await refreshAccessToken(backendBaseUrl, rtForRetry);
  if (!refreshed.ok) {
    const out = NextResponse.json({ detail: refreshed.detail }, { status: 401 });
    clearAuthCookies(out);
    return out;
  }

  upstream = await execute(refreshed.tokens.access_token);
  const out = await toResponse(upstream);
  setAuthCookies(out, refreshed.tokens);
  return out;
}
