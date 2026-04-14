import { proxyBackend } from "@/server/bff/http";

export async function GET() {
  return proxyBackend({ path: "/v2/projects", method: "GET" });
}

export async function POST(req: Request) {
  const payload = await req.json().catch(() => ({}));
  return proxyBackend({ path: "/v2/projects", method: "POST", body: payload });
}
