"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDot, PauseCircle, RefreshCcw } from "lucide-react";

import { buildRunWsUrl, getRunDetail, getWsToken, type RunWsEvent, type WorkflowRunDetail } from "@/generated/api/client";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";

function toneByStatus(status: string): "success" | "warning" | "danger" | "info" | "neutral" {
  const value = String(status || "").toLowerCase();
  if (value === "success") return "success";
  if (value === "failed" || value === "cancelled") return "danger";
  if (value === "waiting_review") return "warning";
  if (value === "running") return "info";
  return "neutral";
}

export function RunTimeline({ runId }: { runId: string }) {
  const { data, isLoading, error, refetch } = useQuery<WorkflowRunDetail>({
    queryKey: ["run", runId],
    queryFn: () => getRunDetail(runId),
    refetchInterval: 15_000
  });
  const [events, setEvents] = useState<RunWsEvent[]>([]);
  const [wsState, setWsState] = useState<"idle" | "connecting" | "open" | "closed" | "error">("idle");
  const [wsError, setWsError] = useState<string | null>(null);
  const cursorRef = useRef(0);

  useEffect(() => {
    let isMounted = true;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = async () => {
      setWsState("connecting");
      try {
        const tokenData = await getWsToken();
        if (!isMounted) return;

        const url = buildRunWsUrl(tokenData.ws_url, runId, tokenData.token, cursorRef.current);
        socket = new WebSocket(url);

        socket.onopen = () => {
          if (!isMounted) return;
          setWsState("open");
          setWsError(null);
        };

        socket.onmessage = (message) => {
          if (!isMounted) return;
          try {
            const payload = JSON.parse(String(message.data || "{}")) as RunWsEvent;
            if (typeof payload.seq === "number") {
              cursorRef.current = Math.max(cursorRef.current, payload.seq);
            }
            if (payload.event_type !== "heartbeat") {
              setEvents((prev) => {
                const exists = prev.some((item) => item.event_id === payload.event_id);
                if (exists) return prev;
                return [payload, ...prev].slice(0, 300);
              });
            }
            if (payload.event_type === "run_completed") {
              refetch();
            }
          } catch {
            // ignore malformed events
          }
        };

        socket.onerror = () => {
          if (!isMounted) return;
          setWsState("error");
          setWsError("实时连接异常，正在尝试重连");
        };

        socket.onclose = () => {
          if (!isMounted) return;
          setWsState("closed");
          reconnectTimer = setTimeout(connect, 2000);
        };
      } catch (err) {
        if (!isMounted) return;
        setWsState("error");
        setWsError(String((err as Error)?.message || "连接失败"));
        reconnectTimer = setTimeout(connect, 3000);
      }
    };

    connect();

    return () => {
      isMounted = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (socket && socket.readyState <= 1) socket.close();
    };
  }, [runId, refetch]);

  const sortedSteps = useMemo(() => {
    return [...(data?.steps || [])].sort((a, b) => Number(a.id) - Number(b.id));
  }, [data]);

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-[var(--font-display)] text-3xl font-semibold text-ink">Run Timeline</h1>
            <p className="mt-1 text-sm text-graphite/70">Run ID: {runId}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge data-tone={toneByStatus(String(data?.status || "idle"))}>{data?.status || "loading"}</Badge>
            <Badge data-tone={wsState === "open" ? "success" : wsState === "error" ? "danger" : "warning"}>
              ws:{wsState}
            </Badge>
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <RefreshCcw className="mr-1.5 h-4 w-4" />刷新
            </Button>
          </div>
        </div>
        {wsError ? <p className="mt-3 text-sm text-rose-700">{wsError}</p> : null}
        {error ? <p className="mt-3 text-sm text-rose-700">{String((error as Error).message || "加载失败")}</p> : null}
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card className="p-6">
          <h2 className="mb-4 text-xl font-semibold text-ink">步骤进度</h2>
          {isLoading ? <p className="text-sm text-graphite/70">加载中...</p> : null}
          <div className="space-y-3">
            {sortedSteps.map((step) => {
              const status = String(step.status || "");
              return (
                <div key={step.id} className="rounded-xl border border-ink/10 bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold text-ink">{step.step_key}</p>
                    <Badge data-tone={toneByStatus(status)}>{status}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-graphite/70">{step.step_type}</p>
                  {step.error_message ? <p className="mt-2 text-xs text-rose-700">{step.error_message}</p> : null}
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="p-6">
          <h2 className="mb-4 text-xl font-semibold text-ink">实时事件流</h2>
          <div className="max-h-[520px] space-y-3 overflow-auto pr-1">
            {events.map((event) => {
              const type = event.event_type;
              return (
                <article key={event.event_id} className="rounded-xl border border-ink/10 bg-white p-3">
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                      {type === "run_completed" ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      ) : type === "step_failed" ? (
                        <AlertTriangle className="h-4 w-4 text-rose-600" />
                      ) : type === "candidate_waiting_review" ? (
                        <PauseCircle className="h-4 w-4 text-amber-600" />
                      ) : (
                        <CircleDot className="h-4 w-4 text-sky-600" />
                      )}
                      {type}
                    </div>
                    <span className="text-xs text-graphite/60">seq {event.seq}</span>
                  </div>
                  <p className="mt-1 text-xs text-graphite/70">{new Date(event.ts).toLocaleString()}</p>
                  <pre className="mt-2 overflow-auto rounded-lg bg-slate-50 p-2 text-xs text-slate-700">
                    {JSON.stringify(event.payload, null, 2)}
                  </pre>
                </article>
              );
            })}
          </div>
        </Card>
      </div>
    </div>
  );
}
