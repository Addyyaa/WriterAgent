export const BFF_ACCESS_COOKIE = "wa_access";
export const BFF_REFRESH_COOKIE = "wa_refresh";

export function getBackendBaseUrl(): string {
  return (process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}

const DEFAULT_BACKEND_BASE_URLS = ["http://127.0.0.1:8080", "http://127.0.0.1:8000"];
const HEALTH_CHECK_TIMEOUT_MS = 800;
const BACKEND_URL_CACHE_TTL_MS = 30_000;

type ResolvedBackendUrlCache = {
  value: string;
  expiresAt: number;
};

let resolvedBackendUrlCache: ResolvedBackendUrlCache | null = null;

function normalizeBaseUrl(input: string): string {
  return String(input || "").trim().replace(/\/$/, "");
}

function getBackendBaseUrlCandidates(): string[] {
  const configured = normalizeBaseUrl(process.env.BACKEND_BASE_URL || "");
  if (!configured) return DEFAULT_BACKEND_BASE_URLS.map(normalizeBaseUrl);

  // If user explicitly points to a non-local backend, do not silently fall back.
  try {
    const host = new URL(configured).hostname;
    const isLocalHost = host === "127.0.0.1" || host === "localhost" || host === "::1";
    if (!isLocalHost) return [configured];
  } catch {
    return [configured];
  }

  const merged = [configured, ...DEFAULT_BACKEND_BASE_URLS.map(normalizeBaseUrl)];
  return Array.from(new Set(merged.filter(Boolean)));
}

async function isHealthyBackend(baseUrl: string): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);
  try {
    const res = await fetch(`${baseUrl}/healthz`, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal
    });
    if (!res.ok) return false;
    const data = await res.json().catch(() => ({}));
    return String((data as { status?: unknown })?.status || "").toLowerCase() === "ok";
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

export async function resolveBackendBaseUrl(): Promise<string> {
  const now = Date.now();
  if (resolvedBackendUrlCache && now < resolvedBackendUrlCache.expiresAt) {
    return resolvedBackendUrlCache.value;
  }

  const candidates = getBackendBaseUrlCandidates();
  for (const candidate of candidates) {
    if (await isHealthyBackend(candidate)) {
      resolvedBackendUrlCache = {
        value: candidate,
        expiresAt: now + BACKEND_URL_CACHE_TTL_MS
      };
      return candidate;
    }
  }

  // fallback: keep deterministic behavior even if health checks all fail
  const fallback = candidates[0] || getBackendBaseUrl();
  resolvedBackendUrlCache = {
    value: fallback,
    expiresAt: now + BACKEND_URL_CACHE_TTL_MS
  };
  return fallback;
}
