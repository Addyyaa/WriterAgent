import type { MetricsJson, Project, RunWsEvent, WorkflowRunDetail } from "@/generated/api/types";

async function parseJson<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message = String((body as { detail?: unknown }).detail || "Request failed");
    throw new Error(message);
  }
  return body as T;
}

export async function getProjects(): Promise<{ items: Project[] }> {
  const res = await fetch("/api/projects", { method: "GET", credentials: "include" });
  return parseJson<{ items: Project[] }>(res);
}

export async function getRunDetail(runId: string): Promise<WorkflowRunDetail> {
  const res = await fetch(`/api/writing/runs/${runId}`, { method: "GET", credentials: "include" });
  return parseJson<WorkflowRunDetail>(res);
}

export async function getSystemMetrics(): Promise<MetricsJson> {
  const res = await fetch("/api/system/metrics", { method: "GET", credentials: "include" });
  return parseJson<MetricsJson>(res);
}

export async function getWsToken(): Promise<{ token: string; ws_url: string }> {
  const res = await fetch("/api/ws-token", { method: "GET", credentials: "include" });
  return parseJson<{ token: string; ws_url: string }>(res);
}

export async function getOpenApiSpec(): Promise<{ paths: Record<string, unknown>; tags?: unknown[] }> {
  const res = await fetch("/api/system/openapi", { method: "GET", credentials: "include" });
  return parseJson<{ paths: Record<string, unknown>; tags?: unknown[] }>(res);
}

export function buildRunWsUrl(baseUrl: string, runId: string, token: string, cursor = 0): string {
  const url = new URL(`${baseUrl.replace(/\/$/, "")}/v2/writing/runs/${runId}/ws`);
  url.searchParams.set("access_token", token);
  url.searchParams.set("cursor", String(cursor));
  return url.toString();
}

export type { Project, WorkflowRunDetail, MetricsJson, RunWsEvent };
