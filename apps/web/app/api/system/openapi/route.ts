import { NextResponse } from "next/server";

import { getBackendBaseUrl } from "@/server/bff/config";
import { getAccessTokenFromCookie } from "@/server/bff/cookies";

export async function GET() {
  const token = await getAccessTokenFromCookie();
  if (!token) {
    return NextResponse.json({ detail: "未登录" }, { status: 401 });
  }

  const res = await fetch(`${getBackendBaseUrl()}/openapi.json`, {
    method: "GET",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`
    }
  });
  const text = await res.text();
  const contentType = res.headers.get("content-type") || "application/json";
  return new NextResponse(text, {
    status: res.status,
    headers: { "content-type": contentType }
  });
}
