import { proxyBackend } from "@/server/bff/http";

export async function GET() {
  return proxyBackend({ path: "/v2/auth/me" });
}
