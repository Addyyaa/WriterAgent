"use client";

import { useQuery } from "@tanstack/react-query";

import { getOpenApiSpec, getSystemMetrics } from "@/generated/api/client";
import { Card } from "@/shared/ui/card";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/90 p-4">
      <p className="text-xs uppercase tracking-[0.12em] text-ocean/70">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-ink">{value}</p>
    </div>
  );
}

export function MetricsDashboard() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["system-metrics"],
    queryFn: getSystemMetrics,
    refetchInterval: 12_000
  });
  const { data: openapi } = useQuery({
    queryKey: ["openapi-index"],
    queryFn: getOpenApiSpec,
    staleTime: 60_000,
    refetchOnWindowFocus: false
  });
  const endpointCount = Object.keys(openapi?.paths || {}).length;
  const endpointPreview = Object.keys(openapi?.paths || {}).slice(0, 20);

  return (
    <div className="space-y-6">
      <Card className="p-6">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h1 className="font-[var(--font-display)] text-3xl font-semibold text-ink">系统指标控制台</h1>
            <p className="mt-1 text-sm text-graphite/70">结构化指标来源: /v2/system/metrics/json</p>
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
        {error ? <p className="mt-4 text-sm text-rose-700">{String((error as Error).message || "加载失败")}</p> : null}
      </Card>

      {data ? (
        <>
          <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Stat label="Queue Depth" value={data.workflow.queue_depth} />
            <Stat label="Run Success" value={data.workflow.runs_success_total} />
            <Stat label="Run Failed" value={data.workflow.runs_failed_total} />
            <Stat label="Skill Executed" value={data.skills.executed_count} />
          </section>

          <section className="grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h2 className="text-lg font-semibold text-ink">Skill Runtime</h2>
              <ul className="mt-3 space-y-2 text-sm text-graphite/80">
                <li>effective_delta: {data.skills.effective_delta}</li>
                <li>fallback_used_count: {data.skills.fallback_used_count}</li>
                <li>no_effect_count: {data.skills.no_effect_count}</li>
                <li>findings_total: {data.skills.findings_total}</li>
                <li>evidence_total: {data.skills.evidence_total}</li>
                <li>external_fact_evidence: {data.skills.fact_external_evidence_total}</li>
              </ul>
            </Card>

            <Card className="p-5">
              <h2 className="text-lg font-semibold text-ink">Schema Governance</h2>
              <ul className="mt-3 space-y-2 text-sm text-graphite/80">
                <li>required_covered_rate: {data.schema_contract.required_covered_rate.toFixed(3)}</li>
                <li>dead_required_count: {data.schema_contract.dead_required_count}</li>
                <li>deprecated_unowned_count: {data.schema_contract.deprecated_unowned_count}</li>
                <li>
                  deprecated_missing_retire_by_count: {data.schema_contract.deprecated_missing_retire_by_count}
                </li>
                <li>invalid_declarations: {data.schema_contract.invalid_consumption_declaration_count}</li>
              </ul>
            </Card>
          </section>

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
          </Card>
        </>
      ) : null}
    </div>
  );
}
