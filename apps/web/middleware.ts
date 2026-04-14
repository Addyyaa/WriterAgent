import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const protectedPrefixes = ["/projects", "/runs", "/metrics"];

export function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const hasAccess = Boolean(req.cookies.get("wa_access")?.value);
  const hasRefresh = Boolean(req.cookies.get("wa_refresh")?.value);
  const hasSession = hasAccess || hasRefresh;

  const needsAuth = protectedPrefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
  if (needsAuth && !hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", path);
    return NextResponse.redirect(url);
  }

  if (path === "/login" && hasSession) {
    const url = req.nextUrl.clone();
    url.pathname = "/projects";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/projects/:path*", "/runs/:path*", "/metrics/:path*", "/login"]
};
