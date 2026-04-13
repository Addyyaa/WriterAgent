import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const protectedPrefixes = ["/projects", "/runs", "/metrics"];

export function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const hasAccess = Boolean(req.cookies.get("wa_access")?.value);

  const needsAuth = protectedPrefixes.some((prefix) => path === prefix || path.startsWith(`${prefix}/`));
  if (needsAuth && !hasAccess) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", path);
    return NextResponse.redirect(url);
  }

  if ((path === "/login" || path === "/register") && hasAccess) {
    const url = req.nextUrl.clone();
    url.pathname = "/projects";
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/projects/:path*", "/runs/:path*", "/metrics/:path*", "/login", "/register"]
};
