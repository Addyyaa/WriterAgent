import { NextResponse } from "next/server";

import { resolveBackendBaseUrl } from "@/server/bff/config";
import { clearAuthCookies, getRefreshTokenFromCookie } from "@/server/bff/cookies";

export async function POST() {
  const refreshToken = await getRefreshTokenFromCookie();
  if (refreshToken) {
    const backendBaseUrl = await resolveBackendBaseUrl();
    await fetch(`${backendBaseUrl}/v2/auth/logout`, {
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
