export type AuthTokens = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export function parseAuthTokens(payload: unknown): AuthTokens | null {
  const data = payload as Record<string, unknown> | null;
  if (!data || typeof data !== "object") return null;

  const access = typeof data.access_token === "string" ? data.access_token : "";
  const refresh = typeof data.refresh_token === "string" ? data.refresh_token : "";
  const expiresRaw = Number(data.expires_in ?? 3600);
  const expires = Number.isFinite(expiresRaw) && expiresRaw > 0 ? expiresRaw : 3600;

  if (!access || !refresh) return null;
  return { access_token: access, refresh_token: refresh, expires_in: expires };
}
