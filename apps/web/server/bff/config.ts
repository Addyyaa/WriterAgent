export const BFF_ACCESS_COOKIE = "wa_access";
export const BFF_REFRESH_COOKIE = "wa_refresh";

export function getBackendBaseUrl(): string {
  return (process.env.BACKEND_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
}
