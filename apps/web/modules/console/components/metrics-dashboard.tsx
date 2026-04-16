"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  getLlmPromptAudit,
  getOpenApiSpec,
  getProjects,
  getRetrievalEvalDaily,
  getSystemMetrics
} from "@/generated/api/client";
import { Card } from "@/shared/ui/card";

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/90 p-4">
      <p className="text-xs uppercase tracking-[0.12em] text-ocean/70">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-ink">{value}</p>
      {hint ? <p className="mt-1 text-[11px] text-graphite/55">{hint}</p> : null}
    </div>
  );
}

function MiniBar({ value, max, color = "bg-ocean" }: { value: number; max: number; color?: string }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 rounded-full bg-slate-200 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-graphite/60 tabular-nums w-10 text-right">{value}</span>
    </div>
  );
}

/** 校验日志中的 llm_task_id（UUID v1–v5） */
const LLM_TASK_ID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isLlmTaskId(value: string): boolean {
  return LLM_TASK_ID_RE.test(String(value || "").trim());
}

function StatusDistribution({ data }: { data: Record<string, number> }) {
  const total = Object.values(data).reduce((s, v) => s + v, 0) || 1;
  const colorMap: Record<string, string> = {
    success: "bg-emerald-500",
    failed: "bg-rose-500",
    cancelled: "bg-slate-400",
    queued: "bg-sky-400",
    running: "bg-amber-400",
    waiting_review: "bg-violet-400",
  };
  return (
    <div className="space-y-2">
      {Object.entries(data).map(([status, count]) => (
        <div key={status} className="flex items-center gap-3">
          <span className="w-28 text-xs text-graphite/70">{status}</span>
          <MiniBar value={count} max={total} color={colorMap[status] || "bg-ocean"} />
        </div>
      ))}
    </div>
  );
}

export function MetricsDashboard() {
  const [promoteLoading, setPromoteLoading] = useState(false);
  const [promoteMessage, setPromoteMessage] = useState<string | null>(null);
  const [promoteError, setPromoteError] = useState<string | null>(null);
  const [abProjectId, setAbProjectId] = useState<string>("");
  const [llmAuditInput, setLlmAuditInput] = useState("");
  const [llmAuditQueryId, setLlmAuditQueryId] = useState<string | null>(null);
  const [llmAuditHint, setLlmAuditHint] = useState<string | null>(null);
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["system-metrics"],
    queryFn: getSystemMetrics,
    refetchInterval: (query) => {
      const message = String((query.state.error as Error | null)?.message || "");
      if (message.includes("需要管理员权限")) return false;
      return 12_000;
    },
    retry: (failureCount, err) => {
      const message = String((err as Error)?.message || "");
      if (message.includes("需要管理员权限")) return false;
      return failureCount < 2;
    }
  });
  const metricsErrorText = String((error as Error)?.message || "");
  const isAdminForbidden = metricsErrorText.includes("需要管理员权限");
  const { data: openapi, error: openapiError } = useQuery({
    queryKey: ["openapi-index"],
    queryFn: getOpenApiSpec,
    staleTime: 60_000,
    refetchOnWindowFocus: false
  });
  const { data: projectsForAb } = useQuery({
    queryKey: ["projects-for-ab"],
    queryFn: getProjects,
    enabled: Boolean(data) && !isAdminForbidden,
    staleTime: 30_000,
  });
  const { data: abEval, error: abEvalError, isFetching: abEvalLoading } = useQuery({
    queryKey: ["retrieval-eval-daily", abProjectId],
    queryFn: () => getRetrievalEvalDaily(abProjectId, 14),
    enabled: Boolean(abProjectId),
    staleTime: 30_000,
  });
  const {
    data: llmAudit,
    error: llmAuditError,
    isFetching: llmAuditLoading,
    refetch: refetchLlmAudit
  } = useQuery({
    queryKey: ["llm-prompt-audit", llmAuditQueryId],
    queryFn: () => getLlmPromptAudit(llmAuditQueryId as string),
    enabled: Boolean(llmAuditQueryId && isLlmTaskId(llmAuditQueryId)),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      const message = String((err as Error)?.message || "");
      if (message.includes("需要管理员权限")) return false;
      if (message.includes("未找到")) return false;
      return failureCount < 2;
    }
  });
  const endpointCount = Object.keys(openapi?.paths || {}).length;
  const endpointPreview = Object.keys(openapi?.paths || {}).slice(0, 20);

  const runLlmAuditLookup = () => {
    setLlmAuditHint(null);
    const tid = llmAuditInput.trim();
    if (!isLlmTaskId(tid)) {
      setLlmAuditHint("请输入日志中出现的合法 llm_task_id（UUID）。");
      return;
    }
    if (llmAuditQueryId === tid) {
      void refetchLlmAudit();
    } else {
      setLlmAuditQueryId(tid);
    }
  };

  const promoteToAdmin = async () => {
    setPromoteMessage(null);
    setPromoteError(null);
    setPromoteLoading(true);
    try {
      const res = await fetch("/api/auth/dev-admin", {
        method: "POST",
        credentials: "include"
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(String(body?.detail || "设置管理员权限失败"));
      setPromoteMessage(String(body?.detail || "管理员权限已设置"));
      await refetch();
    } catch (err) {
      setPromoteError(String((err as Error)?.message || "设置管理员权限失败"));
    } finally {
      setPromoteLoading(false);
    }
  };

  const successRate = data
    ? (() => {
        const total = data.workflow.runs_success_total + data.workflow.runs_failed_total;
        return total > 0 ? ((data.workflow.runs_success_total / total) * 100).toFixed(1) : "—";
      })()
    : "—";

  const projectOptions = projectsForAb?.items || [];

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="font-[var(--font-display)] text-3xl font-semibold text-ink">系统指标控制台</h1>
            <p className="mt-1 text-sm text-graphite/70">
              结构化指标 · 自动刷新 12s
              {data ? <span className="ml-2 text-graphite/50">生成: {new Date(data.generated_at).toLocaleTimeString()}</span> : null}
            </p>
          </div>
          <button
            className="rounded-xl border border-ink/15 px-4 py-2 text-sm font-semibold text-graphite hover:bg-white"
            onClick={() => refetch()}
            type="button"
          >
            手动刷新
          </button>
        </div>
        {isLoading ? <p className="mt-4 text-sm text-graphite/70">加载中...</p> : null}
        {isAdminForbidden ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            当前账号没有管理员权限，无法查看系统级指标。你仍然可以在
            <Link href="/projects" className="ml-1 underline underline-offset-2">
              项目工作台
            </Link>
            发起与管理写作流程。
            <div className="mt-3">
              <button
                className="rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-semibold text-amber-900 hover:bg-amber-100"
                type="button"
                onClick={promoteToAdmin}
                disabled={promoteLoading}
              >
                {promoteLoading ? "设置中..." : "开发环境：将当前账号设为管理员"}
              </button>
            </div>
            {promoteMessage ? <p className="mt-2 text-xs text-emerald-700">{promoteMessage}</p> : null}
            {promoteError ? <p className="mt-2 text-xs text-rose-700">{promoteError}</p> : null}
          </div>
        ) : null}
        {error && !isAdminForbidden ? (
          <p className="mt-4 text-sm text-rose-700">{String((error as Error).message || "加载失败")}</p>
        ) : null}
      </Card>

      {data && !isAdminForbidden ? (
        <>
          {/* 工作流核心指标 */}
          <section>
            <h2 className="mb-3 text-lg font-semibold text-ink">工作流 (Workflow)</h2>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              <Stat label="队列深度" value={data.workflow.queue_depth} hint="待处理 run 数量" />
              <Stat label="成功 Runs" value={data.workflow.runs_success_total} />
              <Stat label="失败 Runs" value={data.workflow.runs_failed_total} />
              <Stat label="失败步骤" value={data.workflow.steps_failed_total} />
              <Stat label="成功率" value={`${successRate}%`} hint="success / (success+failed)" />
            </div>
          </section>

          {/* Run 状态分布 */}
          {Object.keys(data.workflow.recent_by_status || {}).length > 0 && (
            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold text-ink">Run 状态分布</h2>
              <StatusDistribution data={data.workflow.recent_by_status} />
            </Card>
          )}

          {/* 检索与 Skill */}
          <section className="grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold text-ink">检索 (Retrieval)</h2>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="检索轮次" value={data.retrieval.rounds_total} />
                <Stat label="平均覆盖率" value={`${(data.retrieval.coverage_avg * 100).toFixed(1)}%`} />
              </div>
              <div className="mt-4 border-t border-ink/10 pt-4">
                <h3 className="text-sm font-semibold text-ink">检索 A/B（在线评测日聚合）</h3>
                <p className="mt-1 text-xs text-graphite/60">
                  分流由检索层 rerank A/B 配置控制；以下为按项目、按日、按 variant 的曝光/点击聚合（近 14 天）。
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <select
                    className="min-w-[200px] rounded-lg border border-ink/15 bg-white px-2 py-1.5 text-sm"
                    value={abProjectId}
                    onChange={(e) => setAbProjectId(e.target.value)}
                  >
                    <option value="">选择项目…</option>
                    {projectOptions.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.title || p.id}
                      </option>
                    ))}
                  </select>
                </div>
                {abEvalLoading ? <p className="mt-2 text-xs text-graphite/55">加载 A/B 数据…</p> : null}
                {abEvalError ? (
                  <p className="mt-2 text-xs text-rose-700">{String((abEvalError as Error).message)}</p>
                ) : null}
                {abEval && abEval.items.length === 0 ? (
                  <p className="mt-2 text-xs text-graphite/55">暂无聚合记录（尚无检索曝光或未落库）。</p>
                ) : null}
                {abEval && abEval.items.length > 0 ? (
                  <div className="mt-2 max-h-48 overflow-auto rounded-lg border border-ink/10 bg-white">
                    <table className="w-full text-left text-xs">
                      <thead className="sticky top-0 bg-slate-50 text-graphite/70">
                        <tr>
                          <th className="px-2 py-1.5 font-medium">日期</th>
                          <th className="px-2 py-1.5 font-medium">variant</th>
                          <th className="px-2 py-1.5 font-medium">曝光</th>
                          <th className="px-2 py-1.5 font-medium">点击</th>
                          <th className="px-2 py-1.5 font-medium">CTR</th>
                        </tr>
                      </thead>
                      <tbody>
                        {abEval.items.map((row, idx) => (
                          <tr key={`${row.stat_date}-${row.variant}-${idx}`} className="border-t border-ink/5">
                            <td className="px-2 py-1 font-mono text-graphite/80">{row.stat_date}</td>
                            <td className="px-2 py-1 font-semibold text-ink">{row.variant}</td>
                            <td className="px-2 py-1 tabular-nums">{row.impressions}</td>
                            <td className="px-2 py-1 tabular-nums">{row.clicks}</td>
                            <td className="px-2 py-1 tabular-nums">{(row.ctr * 100).toFixed(2)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : null}
              </div>
            </Card>

            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold text-ink">Skill 运行时</h2>
              <ul className="space-y-2 text-sm text-graphite/80">
                <li className="flex justify-between"><span>执行次数</span><span className="font-semibold">{data.skills.executed_count}</span></li>
                <li className="flex justify-between"><span>有效 delta</span><span className="font-semibold">{data.skills.effective_delta}</span></li>
                <li className="flex justify-between"><span>回退次数</span><span className="font-semibold">{data.skills.fallback_used_count}</span></li>
                <li className="flex justify-between"><span>无效果</span><span className="font-semibold">{data.skills.no_effect_count}</span></li>
                <li className="flex justify-between"><span>发现项</span><span className="font-semibold">{data.skills.findings_total}</span></li>
                <li className="flex justify-between"><span>证据项</span><span className="font-semibold">{data.skills.evidence_total}</span></li>
                <li className="flex justify-between"><span>外部事实证据</span><span className="font-semibold">{data.skills.fact_external_evidence_total}</span></li>
              </ul>
              {Object.keys(data.skills.mode_coverage || {}).length > 0 && (
                <div className="mt-3 pt-3 border-t border-ink/10">
                  <p className="text-xs text-graphite/55 mb-2">执行模式分布</p>
                  {Object.entries(data.skills.mode_coverage).map(([mode, count]) => (
                    <div key={mode} className="flex items-center gap-2 mb-1">
                      <span className="w-24 text-xs text-graphite/70">{mode}</span>
                      <MiniBar value={count} max={data.skills.executed_count || 1} color="bg-violet-500" />
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </section>

          {/* Schema & Webhook */}
          <section className="grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold text-ink">Schema 治理</h2>
              <ul className="space-y-2 text-sm text-graphite/80">
                <li className="flex justify-between">
                  <span>required 覆盖率</span>
                  <span className="font-semibold">{(data.schema_contract.required_covered_rate * 100).toFixed(1)}%</span>
                </li>
                <li className="flex justify-between"><span>死 required 字段</span><span className="font-semibold">{data.schema_contract.dead_required_count}</span></li>
                <li className="flex justify-between"><span>deprecated 无主</span><span className="font-semibold">{data.schema_contract.deprecated_unowned_count}</span></li>
                <li className="flex justify-between"><span>deprecated 缺退休日期</span><span className="font-semibold">{data.schema_contract.deprecated_missing_retire_by_count}</span></li>
                <li className="flex justify-between"><span>无效声明</span><span className="font-semibold">{data.schema_contract.invalid_consumption_declaration_count}</span></li>
              </ul>
              <div className="mt-3 pt-3 border-t border-ink/10 text-xs text-graphite/60">
                <span>消费方式: code={data.schema_contract.consumed_by_code_count} · prompt={data.schema_contract.consumed_by_downstream_prompt_count} · audit={data.schema_contract.consumed_by_audit_only_count}</span>
              </div>
            </Card>

            <Card className="p-5">
              <h2 className="mb-3 text-lg font-semibold text-ink">Webhook 投递</h2>
              <div className="grid grid-cols-2 gap-3">
                <Stat label="投递成功" value={data.webhooks.delivery_success_total} />
                <Stat label="投递死信" value={data.webhooks.delivery_dead_total} />
              </div>
            </Card>
          </section>

          {/* LLM 上下文审计（按 llm_task_id） */}
          <Card className="p-5">
            <h2 className="text-lg font-semibold text-ink">LLM 上下文审计</h2>
            <p className="mt-1 text-sm text-graphite/70">
              日志中的任务 ID 与{" "}
              <span className="font-mono text-xs">generate start | llm_task_id=</span> 或{" "}
              <span className="font-mono text-xs">writeragent.llm_audit · [LLM] llm_task_id=</span>{" "}
              一致。默认会先查数据库，无记录时再读仓库内{" "}
              <span className="font-mono text-xs">data/llm_prompt_audit.jsonl</span> 兜底（入库失败或未迁移时常见）。
            </p>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <label className="flex min-w-[280px] flex-1 flex-col gap-1 text-xs text-graphite/65">
                <span className="font-medium text-graphite/80">llm_task_id</span>
                <input
                  className="rounded-lg border border-ink/15 bg-white px-3 py-2 font-mono text-sm text-ink"
                  placeholder="例如 550e8400-e29b-41d4-a716-446655440000"
                  value={llmAuditInput}
                  onChange={(e) => setLlmAuditInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") runLlmAuditLookup();
                  }}
                  autoComplete="off"
                  spellCheck={false}
                  aria-label="LLM 任务 ID"
                />
              </label>
              <button
                type="button"
                className="rounded-xl border border-ink/15 bg-ocean px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50"
                onClick={runLlmAuditLookup}
                disabled={llmAuditLoading}
              >
                {llmAuditLoading ? "查询中…" : "查询"}
              </button>
            </div>
            {llmAuditHint ? <p className="mt-2 text-sm text-amber-800">{llmAuditHint}</p> : null}
            {llmAuditError ? (
              <p className="mt-2 text-sm text-rose-700">{String((llmAuditError as Error).message)}</p>
            ) : null}
            {llmAudit ? (
              <div className="mt-4 space-y-3 text-sm">
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-graphite/75">
                  <span>
                    时间:{" "}
                    <span className="font-mono text-graphite/90">
                      {llmAudit.created_at ?? "—（仅 JSONL 兜底，无入库时间）"}
                    </span>
                  </span>
                  {llmAudit.model ? (
                    <span>
                      模型: <span className="font-semibold text-ink">{llmAudit.model}</span>
                    </span>
                  ) : null}
                  {llmAudit.provider_label ? (
                    <span>
                      提供方: <span className="font-mono">{llmAudit.provider_label}</span>
                    </span>
                  ) : null}
                  {llmAudit.workflow_type ? (
                    <span>
                      workflow: <span className="font-mono">{llmAudit.workflow_type}</span>
                    </span>
                  ) : null}
                  {llmAudit.step_key ? (
                    <span>
                      step: <span className="font-mono">{llmAudit.step_key}</span>
                    </span>
                  ) : null}
                  {llmAudit.role_id ? (
                    <span>
                      role: <span className="font-mono">{llmAudit.role_id}</span>
                    </span>
                  ) : null}
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-graphite/60">system_prompt</p>
                  <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-ink/10 bg-slate-50 p-3 font-mono text-xs text-graphite/90">
                    {llmAudit.system_prompt ?? "（空）"}
                  </pre>
                </div>
                <div>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-graphite/60">user_prompt</p>
                  <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-ink/10 bg-slate-50 p-3 font-mono text-xs text-graphite/90">
                    {llmAudit.user_prompt ?? "（空）"}
                  </pre>
                </div>
                {llmAudit.metadata_json && Object.keys(llmAudit.metadata_json).length > 0 ? (
                  <div>
                    <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-graphite/60">metadata_json</p>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg border border-ink/10 bg-slate-50 p-3 font-mono text-xs text-graphite/90">
                      {JSON.stringify(llmAudit.metadata_json, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </div>
            ) : null}
          </Card>

          {/* API 能力面板 */}
          <Card className="p-5">
            <h2 className="text-lg font-semibold text-ink">API 能力面板</h2>
            <p className="mt-1 text-sm text-graphite/75">
              OpenAPI 可见接口总数: <strong>{endpointCount}</strong>
            </p>
            <div className="mt-3 max-h-72 overflow-auto rounded-xl border border-ink/10 bg-white p-3">
              <ul className="space-y-1 text-sm text-graphite/80">
                {endpointPreview.map((path) => (
                  <li key={path} className="font-mono text-xs">
                    {path}
                  </li>
                ))}
              </ul>
            </div>
            {openapiError ? (
              <p className="mt-3 text-sm text-rose-700">
                OpenAPI 加载失败：{String((openapiError as Error)?.message || "未知错误")}
              </p>
            ) : null}
          </Card>
        </>
      ) : null}
    </div>
  );
}
