"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  PauseCircle,
  RefreshCcw,
  XCircle,
} from "lucide-react";

import {
  buildRunWsUrl,
  cancelRun,
  getRunDetail,
  getWsToken,
  retryRun,
  type RunWsEvent,
  type WorkflowRunDetail,
} from "@/generated/api/client";
import type {
  WriterDraftLiveProgress,
  WorkflowRunMessage,
  WorkflowStep,
} from "@/generated/api/types";
import { Badge } from "@/shared/ui/badge";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { toast } from "@/shared/ui/toast";
import { writerPayloadUsesAssembler } from "@/modules/runs/lib/writer-guidance-meta";

function RunFailedBanner({
  errorCode,
  errorMessage,
}: {
  errorCode: string | null;
  errorMessage: string;
}) {
  const msg = errorMessage || "";
  const isRateLimit =
    msg.includes("429") || msg.toLowerCase().includes("rate limit");
  const isAuth = msg.includes("401") || msg.includes("403");

  let title = "Run 执行失败";
  let hint = "";
  let severity: "rose" | "amber" = "rose";

  if (isRateLimit) {
    title = "LLM API 配额耗尽";
    hint =
      "当前使用的模型已达到免费请求上限。请稍后重试，或在 OpenRouter 中充值以解锁更多配额，然后点击「重试」按钮。";
    severity = "amber";
  } else if (isAuth) {
    title = "LLM API 认证失败";
    hint =
      "请检查环境变量 WRITER_LLM_API_KEY 是否正确配置，然后重启服务后重试。";
  }

  const borderColor =
    severity === "amber" ? "border-amber-300" : "border-rose-300";
  const bgColor = severity === "amber" ? "bg-amber-50" : "bg-rose-50";
  const textColor = severity === "amber" ? "text-amber-900" : "text-rose-900";
  const subtextColor =
    severity === "amber" ? "text-amber-700" : "text-rose-700";

  return (
    <div className={`mt-3 rounded-xl border ${borderColor} ${bgColor} p-4`}>
      <div className="flex items-start gap-2">
        <AlertTriangle className={`mt-0.5 h-5 w-5 shrink-0 ${subtextColor}`} />
        <div className="flex-1">
          <p className={`font-semibold ${textColor}`}>{title}</p>
          {hint && <p className={`mt-1 text-sm ${subtextColor}`}>{hint}</p>}
          <details className="mt-2">
            <summary
              className={`cursor-pointer text-xs ${subtextColor} hover:underline`}
            >
              查看详细错误
            </summary>
            <pre
              className={`mt-1 max-h-32 overflow-auto whitespace-pre-wrap rounded-lg bg-white/60 p-2 text-xs ${textColor}`}
            >
              {errorCode && <span className="font-mono">[{errorCode}] </span>}
              {msg}
            </pre>
          </details>
        </div>
      </div>
    </div>
  );
}

function toneByStatus(
  status: string,
): "success" | "warning" | "danger" | "info" | "neutral" {
  const value = String(status || "").toLowerCase();
  if (value === "success") return "success";
  if (value === "failed" || value === "cancelled") return "danger";
  if (value === "waiting_review") return "warning";
  if (value === "running") return "info";
  return "neutral";
}

const STEP_KEY_LABELS: Record<string, string> = {
  planner_bootstrap: "规划初始化",
  retrieval_context: "上下文检索",
  outline_generation: "大纲生成",
  plot_alignment: "情节对齐",
  character_alignment: "角色对齐",
  world_alignment: "世界观对齐",
  style_alignment: "风格对齐",
  writer_draft: "草稿生成",
  chapter_generation: "章节生成",
  consistency_review: "一致性审校",
  writer_revision: "修订润色",
  revision: "修订",
  persist_artifacts: "结果存档",
};

const WORKFLOW_STEP_TEMPLATES: Record<string, string[]> = {
  writing_full: [
    "planner_bootstrap",
    "retrieval_context",
    "outline_generation",
    "plot_alignment",
    "character_alignment",
    "world_alignment",
    "style_alignment",
    "writer_draft",
    "consistency_review",
    "writer_revision",
    "persist_artifacts",
  ],
  chapter_generation: ["chapter_generation"],
  consistency_review: ["consistency_review"],
  revision: ["writer_revision"],
};

const STEP_TYPE_LABELS: Record<string, string> = {
  workflow: "工作流步骤",
  agent: "Agent 步骤",
  outline_generation: "大纲生成",
  chapter_generation: "章节生成",
  consistency_review: "一致性审校",
  revision: "修订流程",
};

function resolveLabel(
  rawValue: string,
  dictionary: Record<string, string>,
): string {
  const key = String(rawValue || "")
    .trim()
    .toLowerCase();
  if (!key) return "未命名步骤";
  return dictionary[key] || key.replace(/_/g, " ");
}

/** 从步骤 output_json.meta 读取 LLM 审计任务 ID（与日志 / Ops 控制台一致） */
function resolveOutputMetaLlmIds(outputJson: unknown): {
  llm_task_id?: string;
  llm_task_id_prior?: string;
} {
  if (!outputJson || typeof outputJson !== "object") return {};
  const o = outputJson as Record<string, unknown>;
  const meta = o.meta;
  if (!meta || typeof meta !== "object") return {};
  const m = meta as Record<string, unknown>;
  const id = m.llm_task_id;
  const prior = m.llm_task_id_prior;
  return {
    llm_task_id:
      typeof id === "string" && id.trim() ? id.trim() : undefined,
    llm_task_id_prior:
      typeof prior === "string" && prior.trim() ? prior.trim() : undefined,
  };
}

const TRUNC_JSON_STR = 1600;
const TRUNC_JSON_KEYS = 48;
const TRUNC_JSON_ARR = 40;

/** 截断嵌套 JSON，避免步骤 input/output 撑爆页面 */
function truncateDeep(val: unknown, depth = 0): unknown {
  if (depth > 14) return "[嵌套过深已省略]";
  if (val === null || typeof val !== "object") {
    if (typeof val === "string" && val.length > TRUNC_JSON_STR) {
      return `${val.slice(0, TRUNC_JSON_STR)}…【截断，原 ${val.length} 字符】`;
    }
    return val;
  }
  if (Array.isArray(val)) {
    const slice = val.slice(0, TRUNC_JSON_ARR);
    const mapped = slice.map((x) => truncateDeep(x, depth + 1));
    if (val.length > TRUNC_JSON_ARR) {
      mapped.push(`…另有 ${val.length - TRUNC_JSON_ARR} 项`);
    }
    return mapped;
  }
  const obj = val as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  let n = 0;
  for (const [k, v] of Object.entries(obj)) {
    if (n >= TRUNC_JSON_KEYS) {
      out["…"] = `另有 ${Object.keys(obj).length - TRUNC_JSON_KEYS} 个键已省略`;
      break;
    }
    out[k] = truncateDeep(v, depth + 1);
    n += 1;
  }
  return out;
}

function wsEventsForStep(stepId: number, events: RunWsEvent[]): RunWsEvent[] {
  return events.filter((e) => {
    const p = e.payload as Record<string, unknown>;
    const raw = p.step_id ?? p.workflow_step_id;
    if (raw === undefined || raw === null) return false;
    return Number(raw) === stepId;
  });
}

function StepExpandableDiagnostics({
  step,
  wsEvents,
  runMessages,
  runLease,
}: {
  step: WorkflowStep;
  wsEvents: RunWsEvent[];
  runMessages: WorkflowRunMessage[] | undefined;
  runLease?: Pick<WorkflowRunDetail, "heartbeat_at" | "lease_expires_at" | "claimed_by"> | null;
}) {
  const [open, setOpen] = useState(false);
  const scrollRef = useRef<HTMLPreElement>(null);
  const stepId = Number(step.id);

  const snapshotText = useMemo(() => {
    const lines: string[] = [];

    const draftLive = parseWriterDraftLiveProgress(step.input_json);
    if (draftLive && typeof draftLive.attempt === "number") {
      lines.push(
        `→ 当前草稿轮次：第 ${draftLive.attempt}/${draftLive.max_attempts ?? "?"} 次模型调用（以 live_progress 为准）。`,
      );
    }
    lines.push("");
    lines.push(
      `步骤 id=${step.id} key=${step.step_key} type=${step.step_type} status=${step.status} attempt_count=${step.attempt_count}`,
    );
    if (step.role_id) lines.push(`role_id=${step.role_id}`);
    if (step.strategy_version)
      lines.push(`strategy_version=${step.strategy_version}`);
    if (step.prompt_hash)
      lines.push(`prompt_hash=${String(step.prompt_hash).slice(0, 24)}…`);
    if (step.schema_version)
      lines.push(`schema_version=${step.schema_version}`);
    if (step.error_code) lines.push(`error_code=${step.error_code}`);
    if (step.started_at) lines.push(`started_at=${step.started_at}`);
    if (step.finished_at) lines.push(`finished_at=${step.finished_at}`);
    if (step.heartbeat_at) lines.push(`step.heartbeat_at=${step.heartbeat_at}`);
    if (step.last_progress_at) lines.push(`step.last_progress_at=${step.last_progress_at}`);
    if (runLease?.claimed_by) lines.push(`run.claimed_by=${runLease.claimed_by}`);
    if (runLease?.heartbeat_at) lines.push(`run.heartbeat_at=${runLease.heartbeat_at}`);
    if (runLease?.lease_expires_at) lines.push(`run.lease_expires_at=${runLease.lease_expires_at}`);
    lines.push("");
    lines.push("--- input_json（截断后，含 live_progress）---");
    lines.push(JSON.stringify(truncateDeep(step.input_json ?? {}), null, 2));
    lines.push("");
    lines.push("--- output_json（截断后）---");
    lines.push(JSON.stringify(truncateDeep(step.output_json ?? {}), null, 2));
    lines.push("");
    lines.push("--- checkpoint_json（可恢复快照，截断后）---");
    lines.push(JSON.stringify(truncateDeep(step.checkpoint_json ?? {}), null, 2));

    const stepEv = wsEventsForStep(stepId, wsEvents);
    if (stepEv.length > 0) {
      lines.push("");
      lines.push("--- 本步骤相关实时事件（较新在上）---");
      for (const e of [...stepEv].reverse()) {
        lines.push(`[${e.ts}] ${e.event_type} ${JSON.stringify(e.payload)}`);
      }
    }

    const msgs = (runMessages || []).filter(
      (m) => Number(m.workflow_step_id) === stepId,
    );
    if (msgs.length > 0) {
      lines.push("");
      lines.push("--- Agent 消息（按时间）---");
      for (const m of msgs) {
        const c = m.content || "";
        const body = c.length > 2000 ? `${c.slice(0, 2000)}…【截断】` : c;
        lines.push(
          `[${m.created_at || ""}] ${m.role} sender=${m.sender ?? ""} receiver=${m.receiver ?? ""}\n${body}\n---`,
        );
      }
    }

    lines.push("");
    lines.push(
      "--- 刷新 Run 或等待轮询后此处会更新 input/output 快照；WS 事件在重连后可能仅含新游标之后的数据。---",
    );
    return lines.join("\n");
  }, [step, stepId, wsEvents, runMessages, runLease]);

  useEffect(() => {
    if (!open) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [open, snapshotText]);

  return (
    <div className="mt-2 border-t border-ink/10 pt-2">
      <button
        type="button"
        className="flex w-full min-h-[44px] items-center gap-2 rounded-lg px-2 py-2 text-left text-xs font-medium text-ocean hover:bg-sky-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-ocean/40"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0" aria-hidden />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0" aria-hidden />
        )}
        {open ? "收起内部详情" : "展开内部详情与事件日志"}
      </button>
      {open ? (
        <pre
          ref={scrollRef}
          className="mt-2 max-h-72 overflow-auto rounded-lg border border-ink/10 bg-slate-50 p-2 font-mono text-[10px] leading-relaxed text-slate-800"
          tabIndex={0}
        >
          {snapshotText}
        </pre>
      ) : null}
    </div>
  );
}

function parseWriterDraftLiveProgress(
  inputJson: unknown,
): WriterDraftLiveProgress | null {
  if (!inputJson || typeof inputJson !== "object") return null;
  const raw = (inputJson as Record<string, unknown>).live_progress;
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (String(o.kind || "") !== "writer_draft_llm") return null;
  return {
    kind: "writer_draft_llm",
    attempt: typeof o.attempt === "number" ? o.attempt : undefined,
    max_attempts:
      typeof o.max_attempts === "number" ? o.max_attempts : undefined,
    generation_mode:
      typeof o.generation_mode === "string" ? o.generation_mode : undefined,
    issue:
      o.issue === null || typeof o.issue === "string"
        ? (o.issue as string | null)
        : undefined,
    schema_min_content_len:
      typeof o.schema_min_content_len === "number"
        ? o.schema_min_content_len
        : undefined,
    pulse_at: typeof o.pulse_at === "string" ? o.pulse_at : undefined,
    llm_timeout_seconds:
      typeof o.llm_timeout_seconds === "number"
        ? o.llm_timeout_seconds
        : undefined,
  };
}

const GENERATION_MODE_LABEL: Record<string, string> = {
  full_regenerate: "全文重写",
  expand_short_draft: "短文扩写",
};

const ISSUE_LABEL: Record<string, string> = {
  too_short: "字数偏少",
  too_long: "字数偏多",
};

/** 将秒数格式化为可读中文时长（用于「已超时多久」等累计计时，避免误以为上限是几千秒） */
function formatDurationCn(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s} 秒`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return rem === 0 ? `${m} 分钟` : `${m} 分 ${rem} 秒`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return mm === 0 ? `${h} 小时` : `${h} 小时 ${mm} 分`;
}

/** 基于 pulse_at 与单次 LLM 读超时做本地倒计时（每秒刷新） */
function LlmReadCountdown({
  pulseAt,
  timeoutSeconds,
}: {
  pulseAt: string;
  timeoutSeconds: number;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [pulseAt, timeoutSeconds]);
  const start = Date.parse(pulseAt);
  if (!Number.isFinite(start) || timeoutSeconds <= 0) {
    return <span className="text-graphite/70">等待模型响应…</span>;
  }
  const deadline = start + timeoutSeconds * 1000;
  const left = Math.max(0, Math.ceil((deadline - now) / 1000));
  if (left > 0) {
    return (
      <span className="font-mono text-sky-900">单次请求估时剩余 {left}s</span>
    );
  }
  const overdueSec = Math.max(0, Math.floor((now - deadline) / 1000));
  return (
    <span
      className="text-sky-900"
      title={`自单次读估时期满起已多等 ${overdueSec}s`}
    >
      估时已满，已多等 {formatDurationCn(overdueSec)}
      <span className="ml-1 font-normal text-sky-800">
        · 或仍排队/重试；久无进展可查 worker 或取消 Run
      </span>
    </span>
  );
}

function WriterDraftRetryBanner({ live }: { live: WriterDraftLiveProgress }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [live.pulse_at]);
  const attempt = live.attempt ?? 1;
  const max = live.max_attempts ?? 1;
  const modeKey = String(live.generation_mode || "");
  const modeLabel = GENERATION_MODE_LABEL[modeKey] || modeKey || "—";
  const issueKey = live.issue ? String(live.issue) : "";
  const issueLabel = issueKey ? ISSUE_LABEL[issueKey] || issueKey : "首轮生成";
  const timeoutSec = live.llm_timeout_seconds ?? 120;
  const pulseAt = live.pulse_at || new Date().toISOString();
  const pulseMs = Date.parse(pulseAt);
  const pulseAgeSec = Number.isFinite(pulseMs)
    ? Math.max(0, Math.floor((now - pulseMs) / 1000))
    : 0;
  /** 服务端仅在发起每次 LLM 调用前更新 pulse；久未更新则可能是 worker 卡住或已崩溃 */
  const pulseStale = pulseAgeSec > timeoutSec + 180;
  return (
    <div
      className="mb-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-950"
      aria-live="polite"
    >
      <p className="font-semibold text-sky-950">
        草稿字数/Schema 第 {attempt}/{max} 次模型调用
        <span className="ml-2 font-normal text-sky-800">
          {modeLabel} · {issueLabel}
          {typeof live.schema_min_content_len === "number"
            ? ` · schema正文下限 ${live.schema_min_content_len}`
            : ""}
        </span>
      </p>
      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sky-800">
        <LlmReadCountdown pulseAt={pulseAt} timeoutSeconds={timeoutSec} />
      </p>
      {pulseStale ? (
        <p
          className="mt-1.5 rounded-md border border-amber-200 bg-amber-50/90 px-2 py-1 text-amber-950"
          title={`距上次心跳 ${pulseAgeSec}s`}
        >
          自第 {attempt} 次调用起无新心跳 · {formatDurationCn(pulseAgeSec)} ·
          请确认 <span className="font-mono">run_orchestrator_worker</span>{" "}
          或取消/重试
        </p>
      ) : null}
    </div>
  );
}

export function RunTimeline({ runId }: { runId: string }) {
  const { data, isLoading, error, refetch } = useQuery<WorkflowRunDetail>({
    queryKey: ["run", runId],
    queryFn: () => getRunDetail(runId),
    refetchInterval: (query) => {
      const status = String(
        (query.state.data as WorkflowRunDetail | undefined)?.status || "",
      ).toLowerCase();
      if (["success", "failed", "cancelled"].includes(status)) return false;
      if (status === "running") return 3_000;
      return 5_000;
    },
  });
  const [events, setEvents] = useState<RunWsEvent[]>([]);
  const [wsState, setWsState] = useState<
    "idle" | "connecting" | "open" | "closed" | "error"
  >("idle");
  const [wsError, setWsError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<"retry" | "cancel" | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const cursorRef = useRef(0);

  const handleRetry = async () => {
    setActionLoading("retry");
    setActionError(null);
    try {
      await retryRun(runId);
      toast.success("已重新入队，等待 worker 执行");
      refetch();
    } catch (err) {
      const msg = String((err as Error)?.message || "重试失败");
      setActionError(msg);
      toast.error(msg);
    } finally {
      setActionLoading(null);
    }
  };

  const handleCancel = async () => {
    setActionLoading("cancel");
    setActionError(null);
    try {
      await cancelRun(runId);
      toast.info("run 已取消");
      refetch();
    } catch (err) {
      const msg = String((err as Error)?.message || "取消失败");
      setActionError(msg);
      toast.error(msg);
    } finally {
      setActionLoading(null);
    }
  };

  useEffect(() => {
    let isMounted = true;
    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = async () => {
      setWsState("connecting");
      try {
        const tokenData = await getWsToken();
        if (!isMounted) return;

        const url = buildRunWsUrl(
          tokenData.ws_url,
          runId,
          tokenData.token,
          cursorRef.current,
        );
        socket = new WebSocket(url);

        socket.onopen = () => {
          if (!isMounted) return;
          setWsState("open");
          setWsError(null);
        };

        socket.onmessage = (message) => {
          if (!isMounted) return;
          try {
            const payload = JSON.parse(
              String(message.data || "{}"),
            ) as RunWsEvent;
            if (typeof payload.seq === "number") {
              cursorRef.current = Math.max(cursorRef.current, payload.seq);
            }
            if (payload.event_type !== "heartbeat") {
              setEvents((prev) => {
                const exists = prev.some(
                  (item) => item.event_id === payload.event_id,
                );
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

  const expectedSteps = useMemo(() => {
    const workflow = String(data?.workflow_type || "").toLowerCase();
    return WORKFLOW_STEP_TEMPLATES[workflow] || [];
  }, [data?.workflow_type]);

  const stepStatusByKey = useMemo(() => {
    const map = new Map<string, string>();
    for (const step of sortedSteps) {
      map.set(
        String(step.step_key || "").toLowerCase(),
        String(step.status || "").toLowerCase(),
      );
    }
    return map;
  }, [sortedSteps]);

  const queuedTooLongHint = useMemo(() => {
    if (!data) return null;
    if (String(data.status) !== "queued") return null;
    if ((data.steps || []).length > 0) return null;
    const createdAt = Date.parse(String(data.created_at || ""));
    if (!Number.isFinite(createdAt)) return null;
    const elapsedMs = Date.now() - createdAt;
    if (elapsedMs < 15_000) return null;
    return {
      elapsedSeconds: Math.floor(elapsedMs / 1000),
    };
  }, [data]);

  const progressInfo = useMemo(() => {
    const totalExpected = expectedSteps.length || sortedSteps.length || 1;
    const completedCount = sortedSteps.filter(
      (s) => String(s.status || "").toLowerCase() === "success",
    ).length;
    const pct = Math.min(
      100,
      Math.round((completedCount / totalExpected) * 100),
    );
    return { completedCount, totalExpected, pct };
  }, [sortedSteps, expectedSteps]);

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-[var(--font-display)] text-3xl font-semibold text-ink">
              Run Timeline
            </h1>
            <p className="mt-1 text-sm text-graphite/70">Run ID: {runId}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge data-tone={toneByStatus(String(data?.status || "idle"))}>
              {data?.status || "loading"}
            </Badge>
            <Badge
              data-tone={
                wsState === "open"
                  ? "success"
                  : wsState === "error"
                    ? "danger"
                    : "warning"
              }
            >
              ws:{wsState}
            </Badge>
            <Button variant="secondary" size="sm" onClick={() => refetch()}>
              <RefreshCcw className="mr-1.5 h-4 w-4" />
              刷新
            </Button>
            {data &&
              ["failed", "cancelled"].includes(
                String(data.status || "").toLowerCase(),
              ) && (
                <Button
                  size="sm"
                  onClick={handleRetry}
                  disabled={actionLoading !== null}
                >
                  {actionLoading === "retry" ? (
                    <RefreshCcw className="mr-1.5 h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCcw className="mr-1.5 h-4 w-4" />
                  )}
                  重试
                </Button>
              )}
            {data &&
              ["queued", "running"].includes(
                String(data.status || "").toLowerCase(),
              ) && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={handleCancel}
                  disabled={actionLoading !== null}
                >
                  <XCircle className="mr-1.5 h-4 w-4" />
                  取消
                </Button>
              )}
          </div>
        </div>
        {wsError ? (
          <p className="mt-3 text-sm text-rose-700">{wsError}</p>
        ) : null}
        {error ? (
          <p className="mt-3 text-sm text-rose-700">
            {String((error as Error).message || "加载失败")}
          </p>
        ) : null}
        {actionError ? (
          <p className="mt-3 text-sm text-rose-700">{actionError}</p>
        ) : null}
        {queuedTooLongHint ? (
          <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            当前 run 已排队 {queuedTooLongHint.elapsedSeconds}
            s，但尚未进入步骤，通常表示 worker 未启动。
            <p className="mt-2 font-mono text-xs text-amber-900">
              ./venv/bin/python scripts/run_orchestrator_worker.py
            </p>
            <p className="mt-1 text-xs">
              或重启 API 并设置
              WRITER_ORCH_ENABLE_AUTO_WORKER=1（当前版本默认开启）。
            </p>
          </div>
        ) : null}
        {data &&
          String(data.status || "").toLowerCase() === "failed" &&
          data.error_message && (
            <RunFailedBanner
              errorCode={data.error_code}
              errorMessage={data.error_message}
            />
          )}
        {data &&
          String(data.status || "").toLowerCase() === "waiting_review" && (
            <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <p className="font-semibold">等待审批章节候选</p>
              <p className="mt-1 leading-relaxed">
                当前工作流已生成章节候选，需在项目工作台对候选执行「通过」或「驳回」后，才会继续执行「一致性审校」及后续步骤。进度条若停在此处，并非故障，而是等待人工确认。
              </p>
            </div>
          )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <Card className="p-6">
          <h2 className="mb-2 text-xl font-semibold text-ink">步骤进度</h2>
          {!isLoading && sortedSteps.length > 0 && (
            <div className="mb-4">
              <div className="flex items-center justify-between text-xs text-graphite/70 mb-1">
                <span>
                  {progressInfo.completedCount}/{progressInfo.totalExpected}{" "}
                  步完成
                </span>
                <span>{progressInfo.pct}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-slate-200 overflow-hidden">
                <div
                  className="h-full rounded-full bg-ocean transition-all duration-500"
                  style={{ width: `${progressInfo.pct}%` }}
                />
              </div>
            </div>
          )}
          {isLoading ? (
            <p className="text-sm text-graphite/70">加载中...</p>
          ) : null}
          <div className="max-h-[520px] space-y-3 overflow-auto pr-1">
            {sortedSteps.map((step) => {
              const status = String(step.status || "");
              const stepKeyRaw = String(step.step_key || "");
              const stepTypeRaw = String(step.step_type || "");
              const stepKeyLabel = resolveLabel(stepKeyRaw, STEP_KEY_LABELS);
              const stepTypeLabel = resolveLabel(stepTypeRaw, STEP_TYPE_LABELS);
              const isRunning = status === "running";
              const isAgent = stepTypeRaw === "agent";
              const writerLive = isRunning
                ? parseWriterDraftLiveProgress(step.input_json)
                : null;
              const writerGuidance =
                step.output_json &&
                typeof step.output_json === "object" &&
                "writer_guidance" in step.output_json
                  ? (step.output_json as Record<string, unknown>).writer_guidance
                  : undefined;
              const showAssemblerContextHint =
                stepKeyRaw === "writer_draft" &&
                String(status).toLowerCase() === "success" &&
                writerPayloadUsesAssembler(writerGuidance);
              const llmIds = resolveOutputMetaLlmIds(step.output_json);
              return (
                <div
                  key={step.id}
                  className={`rounded-xl border bg-white p-3 transition-all ${isRunning ? "border-sky-300 shadow-sm shadow-sky-100" : "border-ink/10"}`}
                >
                  {writerLive ? (
                    <WriterDraftRetryBanner live={writerLive} />
                  ) : null}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2">
                      {isRunning && (
                        <span className="relative flex h-2.5 w-2.5">
                          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-75" />
                          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-sky-500" />
                        </span>
                      )}
                      <div>
                        <p className="font-semibold text-ink">{stepKeyLabel}</p>
                        <p className="mt-0.5 font-mono text-[11px] text-graphite/55">
                          {stepKeyRaw}
                        </p>
                      </div>
                    </div>
                    <Badge data-tone={toneByStatus(status)}>{status}</Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs text-graphite/70">
                    {isAgent && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-violet-50 px-2 py-0.5 text-violet-700">
                        <CircleDot className="h-3 w-3" />
                        Agent
                      </span>
                    )}
                    <span>{stepTypeLabel}</span>
                    <span className="font-mono text-graphite/50">
                      {stepTypeRaw}
                    </span>
                  </div>
                  {llmIds.llm_task_id ? (
                    <div
                      className="mt-1.5 rounded-lg border border-ink/8 bg-slate-50/90 px-2 py-1.5 text-[11px] leading-snug text-graphite/80"
                      title="可在系统指标控制台「LLM 上下文审计」中按此 ID 查询发往模型的上下文"
                    >
                      <span className="text-graphite/55">llm_task_id</span>{" "}
                      <span className="break-all font-mono text-graphite/90">
                        {llmIds.llm_task_id}
                      </span>
                      {llmIds.llm_task_id_prior ? (
                        <>
                          <span className="mx-1 text-graphite/35">·</span>
                          <span className="text-graphite/55">压缩重试前</span>{" "}
                          <span className="break-all font-mono text-graphite/75">
                            {llmIds.llm_task_id_prior}
                          </span>
                        </>
                      ) : null}
                    </div>
                  ) : null}
                  {showAssemblerContextHint ? (
                    <p
                      className="mt-1.5 text-xs text-graphite/65"
                      title="output_json.writer_guidance.prompt_payload_via_assembler"
                    >
                      草稿上下文已由 Assembler
                      分区注入（请用 prompt_payload_via_assembler，勿依赖
                      has_guidance_text）
                    </p>
                  ) : null}
                  {isRunning && (
                    <p className="mt-2 text-xs text-sky-700 animate-pulse">
                      正在执行…
                    </p>
                  )}
                  {step.error_message ? (
                    <div className="mt-2 rounded-lg bg-rose-50 px-2.5 py-1.5 text-xs text-rose-700">
                      {step.error_message.includes("429") ||
                      step.error_message
                        .toLowerCase()
                        .includes("rate limit") ? (
                        <>
                          <span className="font-semibold">LLM 配额耗尽</span> —
                          模型请求频率超限，请稍后重试或充值 API 配额。
                        </>
                      ) : step.error_message.includes("401") ||
                        step.error_message.includes("403") ? (
                        <>
                          <span className="font-semibold">认证失败</span> —
                          请检查 LLM API Key 配置。
                        </>
                      ) : (
                        step.error_message
                      )}
                    </div>
                  ) : null}
                  <StepExpandableDiagnostics
                    step={step}
                    wsEvents={events}
                    runMessages={data?.messages}
                    runLease={
                      data
                        ? {
                            heartbeat_at: data.heartbeat_at,
                            lease_expires_at: data.lease_expires_at,
                            claimed_by: data.claimed_by,
                          }
                        : null
                    }
                  />
                </div>
              );
            })}
            {!isLoading &&
            sortedSteps.length === 0 &&
            expectedSteps.length > 0 ? (
              <div className="space-y-2">
                {expectedSteps.map((stepKey, index) => {
                  const status = stepStatusByKey.get(stepKey) || "queued";
                  return (
                    <div
                      key={`${stepKey}-${index}`}
                      className="rounded-xl border border-dashed border-ink/20 bg-white/70 p-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <p className="font-semibold text-ink">
                            {resolveLabel(stepKey, STEP_KEY_LABELS)}
                          </p>
                          <p className="mt-0.5 font-mono text-[11px] text-graphite/55">
                            {stepKey}
                          </p>
                        </div>
                        <Badge data-tone={toneByStatus(status)}>
                          {status === "queued" ? "待执行" : status}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : null}
            {!isLoading &&
            sortedSteps.length === 0 &&
            expectedSteps.length === 0 ? (
              <p className="text-sm text-graphite/70">
                当前 run 还没有步骤数据。
              </p>
            ) : null}
          </div>
        </Card>

        <Card className="p-6">
          <h2 className="mb-4 text-xl font-semibold text-ink">实时事件流</h2>
          <div className="max-h-[520px] space-y-3 overflow-auto pr-1">
            {events.map((event) => {
              const type = event.event_type;
              return (
                <article
                  key={event.event_id}
                  className="rounded-xl border border-ink/10 bg-white p-3"
                >
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
                    <span className="text-xs text-graphite/60">
                      seq {event.seq}
                    </span>
                  </div>
                  <p className="mt-1 text-xs text-graphite/70">
                    {new Date(event.ts).toLocaleString()}
                  </p>
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
