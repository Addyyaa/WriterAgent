import type { NextResponse } from "next/server";
import { cookies } from "next/headers";

import { BFF_ACCESS_COOKIE, BFF_REFRESH_COOKIE } from "@/server/bff/config";

const commonCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/"
};

export async function getAccessTokenFromCookie(): Promise<string | null> {
  const store = await cookies();
  const value = store.get(BFF_ACCESS_COOKIE)?.value;
  return value ? String(value) : null;
}

export async function getRefreshTokenFromCookie(): Promise<string | null> {
  const store = await cookies();
  const value = store.get(BFF_REFRESH_COOKIE)?.value;
  return value ? String(value) : null;
}

export function setAuthCookies(
  res: NextResponse,
  payload: { access_token: string; refresh_token: string; expires_in?: number }
): void {
  const accessMaxAge = Math.max(60, Number(payload.expires_in || 3600));
  const refreshMaxAge = 60 * 60 * 24 * 30;
  res.cookies.set(BFF_ACCESS_COOKIE, payload.access_token, { ...commonCookieOptions, maxAge: accessMaxAge });
  res.cookies.set(BFF_REFRESH_COOKIE, payload.refresh_token, { ...commonCookieOptions, maxAge: refreshMaxAge });
}

export function clearAuthCookies(res: NextResponse): void {
  res.cookies.set(BFF_ACCESS_COOKIE, "", { ...commonCookieOptions, maxAge: 0 });
  res.cookies.set(BFF_REFRESH_COOKIE, "", { ...commonCookieOptions, maxAge: 0 });
}
