import { NextResponse } from "next/server";

import { resolveBackendBaseUrl } from "@/server/bff/config";
import { clearAuthCookies, getRefreshTokenFromCookie, setAuthCookies } from "@/server/bff/cookies";
import { refreshAuthFromCookiesSingleFlight } from "@/server/bff/refresh-single-flight";

export async function POST() {
  if (!(await getRefreshTokenFromCookie())) {
    return NextResponse.json({ detail: "缺少 refresh token" }, { status: 401 });
  }

  const backendBaseUrl = await resolveBackendBaseUrl();
  const result = await refreshAuthFromCookiesSingleFlight(backendBaseUrl);
  if (!result.ok) {
    const out = NextResponse.json({ detail: result.detail }, { status: 401 });
    clearAuthCookies(out);
    return out;
  }

  const out = NextResponse.json({ ok: true, user: result.user });
  setAuthCookies(out, result.tokens);
  return out;
}
