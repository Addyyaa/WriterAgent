import { NextResponse } from "next/server";

import { getBackendBaseUrl } from "@/server/bff/config";
import {
  clearAuthCookies,
  getAccessTokenFromCookie,
  getRefreshTokenFromCookie,
  setAuthCookies
} from "@/server/bff/cookies";

type ProxyOptions = {
  path: string;
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  passThroughHeaders?: Record<string, string>;
};

export async function proxyBackend(options: ProxyOptions): Promise<NextResponse> {
  const token = await getAccessTokenFromCookie();
  if (!token) return NextResponse.json({ detail: "未登录" }, { status: 401 });

  const execute = (accessToken: string) =>
    fetch(`${getBackendBaseUrl()}${options.path}`, {
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
  if (upstream.status !== 401) return toResponse(upstream);

  const refreshToken = await getRefreshTokenFromCookie();
  if (!refreshToken) return toResponse(upstream);

  const refreshRes = await fetch(`${getBackendBaseUrl()}/v2/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store"
  });

  const refreshBody = await refreshRes.json().catch(() => ({}));
  if (!refreshRes.ok) {
    const out = NextResponse.json({ detail: String(refreshBody?.detail || "登录态已过期") }, { status: 401 });
    clearAuthCookies(out);
    return out;
  }

  const freshAccessToken = String(refreshBody.access_token || "");
  const freshRefreshToken = String(refreshBody.refresh_token || "");
  if (!freshAccessToken || !freshRefreshToken) {
    const out = NextResponse.json({ detail: "刷新返回数据不完整" }, { status: 401 });
    clearAuthCookies(out);
    return out;
  }

  upstream = await execute(freshAccessToken);
  const out = await toResponse(upstream);
  setAuthCookies(out, {
    access_token: freshAccessToken,
    refresh_token: freshRefreshToken,
    expires_in: Number(refreshBody.expires_in || 3600)
  });
  return out;
}
