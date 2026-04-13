import { proxyBackend } from "@/server/bff/http";

export async function GET() {
  return proxyBackend({ path: "/v2/system/metrics/json", method: "GET" });
}
