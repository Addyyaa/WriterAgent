import { NextResponse } from "next/server";

import { getBackendBaseUrl } from "@/server/bff/config";
import { clearAuthCookies, getRefreshTokenFromCookie } from "@/server/bff/cookies";

export async function POST() {
  const refreshToken = await getRefreshTokenFromCookie();
  if (refreshToken) {
    await fetch(`${getBackendBaseUrl()}/v2/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store"
    }).catch(() => null);
  }
  const out = NextResponse.json({ ok: true });
  clearAuthCookies(out);
  return out;
}
