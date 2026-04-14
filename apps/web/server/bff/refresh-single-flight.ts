import { parseAuthTokens, type AuthTokens } from "@/server/bff/auth-tokens";
import { getRefreshTokenFromCookie } from "@/server/bff/cookies";

export type RefreshFromCookiesResult =
  | { ok: true; tokens: AuthTokens; user: unknown }
  | { ok: false; detail: string };

/**
 * 合并同一进程内并发 refresh：后端轮换 refresh_token 时，并行请求若各刷一次会导致除首请求外全部 401，
 * BFF 再清 cookie，表现为「突然掉登录」。此处只让首个请求访问 /v2/auth/refresh，其余等待同一结果。
 */
let inflight: Promise<RefreshFromCookiesResult> | null = null;

export function refreshAuthFromCookiesSingleFlight(backendBaseUrl: string): Promise<RefreshFromCookiesResult> {
  if (inflight) {
    return inflight;
  }
  const leader = (async (): Promise<RefreshFromCookiesResult> => {
    const refreshToken = await getRefreshTokenFromCookie();
    if (!refreshToken) {
      return { ok: false, detail: "缺少 refresh token" };
    }
    const refreshRes = await fetch(`${backendBaseUrl}/v2/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store"
    });
    const refreshBody = await refreshRes.json().catch(() => ({}));
    if (!refreshRes.ok) {
      return { ok: false, detail: String(refreshBody?.detail || refreshBody?.error || "登录态已过期") };
    }
    const refreshed = parseAuthTokens(refreshBody);
    if (!refreshed) {
      return { ok: false, detail: "刷新返回数据不完整" };
    }
    const user =
      refreshBody && typeof refreshBody === "object" && "user" in refreshBody
        ? (refreshBody as { user?: unknown }).user
        : undefined;
    return { ok: true, tokens: refreshed, user };
  })();
  inflight = leader;
  void leader.finally(() => {
    if (inflight === leader) {
      inflight = null;
    }
  });
  return leader;
}
