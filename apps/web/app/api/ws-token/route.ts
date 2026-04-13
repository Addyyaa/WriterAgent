import { NextResponse } from "next/server";

import { getBackendBaseUrl } from "@/server/bff/config";
import { getAccessTokenFromCookie } from "@/server/bff/cookies";

export async function GET() {
  const token = await getAccessTokenFromCookie();
  if (!token) {
    return NextResponse.json({ detail: "未登录" }, { status: 401 });
  }
  return NextResponse.json({
    token,
    ws_url: getBackendBaseUrl()
  });
}
