import { NextResponse } from "next/server";

import { parseAuthTokens } from "@/server/bff/auth-tokens";
import { resolveBackendBaseUrl } from "@/server/bff/config";
import {
  clearAuthCookies,
  getAccessTokenFromCookie,
  getRefreshTokenFromCookie,
  setAuthCookies
} from "@/server/bff/cookies";

function parseDetail(payload: unknown, fallback: string): string {
  const data = payload as Record<string, unknown> | null;
  return String(data?.detail || data?.error || fallback);
}

async function refreshAccessToken(backendBaseUrl: string, refreshToken: string) {
  const refreshRes = await fetch(`${backendBaseUrl}/v2/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store"
  });
  const refreshBody = await refreshRes.json().catch(() => ({}));
  if (!refreshRes.ok) return { ok: false as const, detail: parseDetail(refreshBody, "登录态已过期") };
  const refreshed = parseAuthTokens(refreshBody);
  if (!refreshed) return { ok: false as const, detail: "刷新登录态失败" };
  return { ok: true as const, refreshed };
}

async function ensureValidAccessToken(backendBaseUrl: string) {
  let accessToken = await getAccessTokenFromCookie();
  const refreshToken = await getRefreshTokenFromCookie();
  let refreshedPayload: { access_token: string; refresh_token: string; expires_in: number } | null = null;

  if (!accessToken && refreshToken) {
    const refreshed = await refreshAccessToken(backendBaseUrl, refreshToken);
    if (!refreshed.ok) return { ok: false as const, detail: refreshed.detail, clearCookies: true };
    refreshedPayload = refreshed.refreshed;
    accessToken = refreshed.refreshed.access_token;
  }
  if (!accessToken) return { ok: false as const, detail: "未登录", clearCookies: true };

  const meRes = await fetch(`${backendBaseUrl}/v2/auth/me`, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store"
  });
  if (meRes.ok) {
    const meBody = await meRes.json().catch(() => ({}));
    return { ok: true as const, accessToken, refreshedPayload, meBody };
  }

  if (!refreshToken) {
    const body = await meRes.json().catch(() => ({}));
    return { ok: false as const, detail: parseDetail(body, "登录态已过期"), clearCookies: true };
  }

  const refreshed = await refreshAccessToken(backendBaseUrl, refreshToken);
  if (!refreshed.ok) return { ok: false as const, detail: refreshed.detail, clearCookies: true };
  accessToken = refreshed.refreshed.access_token;
  refreshedPayload = refreshed.refreshed;

  const meRetry = await fetch(`${backendBaseUrl}/v2/auth/me`, {
    method: "GET",
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store"
  });
  const meRetryBody = await meRetry.json().catch(() => ({}));
  if (!meRetry.ok) {
    return { ok: false as const, detail: parseDetail(meRetryBody, "鉴权失败"), clearCookies: true };
  }
  return { ok: true as const, accessToken, refreshedPayload, meBody: meRetryBody };
}

export async function POST() {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json({ detail: "生产环境禁用该入口" }, { status: 403 });
  }

  const backendBaseUrl = await resolveBackendBaseUrl();
  const ensured = await ensureValidAccessToken(backendBaseUrl);
  if (!ensured.ok) {
    const out = NextResponse.json({ detail: ensured.detail }, { status: 401 });
    if (ensured.clearCookies) clearAuthCookies(out);
    return out;
  }

  const me = (ensured.meBody as { user?: Record<string, unknown> } | null)?.user || {};
  const userId = String(me.id || "").trim();
  if (!userId) {
    const out = NextResponse.json({ detail: "无法识别当前用户" }, { status: 400 });
    if (ensured.refreshedPayload) setAuthCookies(out, ensured.refreshedPayload);
    return out;
  }

  const currentPrefs = (me.preferences as Record<string, unknown>) || {};
  const patchRes = await fetch(`${backendBaseUrl}/v2/users/${userId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${ensured.accessToken}`
    },
    body: JSON.stringify({
      preferences: {
        ...currentPrefs,
        is_admin: true
      }
    }),
    cache: "no-store"
  });
  const patchBody = await patchRes.json().catch(() => ({}));
  if (!patchRes.ok) {
    const out = NextResponse.json({ detail: parseDetail(patchBody, "设置管理员权限失败") }, { status: patchRes.status });
    if (ensured.refreshedPayload) setAuthCookies(out, ensured.refreshedPayload);
    return out;
  }

  const out = NextResponse.json({
    ok: true,
    detail: "当前账号已设为管理员",
    user: patchBody
  });
  if (ensured.refreshedPayload) setAuthCookies(out, ensured.refreshedPayload);
  return out;
}
