"use client";

import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { PlayCircle, Rocket } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { getProjects } from "@/generated/api/client";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { EmptyState } from "@/shared/ui/empty-state";

const runSchema = z.object({
  project_id: z.string().min(1, "请选择项目"),
  writing_goal: z.string().min(4, "请填写写作目标"),
  workflow_type: z.string().default("writing_full")
});

type RunForm = z.infer<typeof runSchema>;

export function ProjectWorkbench() {
  const { data, isLoading, error } = useQuery({ queryKey: ["projects"], queryFn: getProjects });

  const { register, handleSubmit, formState, reset } = useForm<RunForm>({
    resolver: zodResolver(runSchema),
    defaultValues: {
      workflow_type: "writing_full"
    }
  });

  const onSubmit = handleSubmit(async (values) => {
    const res = await fetch("/api/writing/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({
        project_id: values.project_id,
        workflow_type: values.workflow_type,
        writing_goal: values.writing_goal,
        target_words: 1200
      })
    });

    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(String(body?.detail || "创建 run 失败"));
    }
    const runId = String(body.run_id || "").trim();
    if (runId) {
      window.location.href = `/runs/${runId}`;
      return;
    }
    reset();
  });

  return (
    <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
      <Card className="p-6">
        <div className="mb-5 flex items-center justify-between">
          <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink">项目资产</h2>
          <span className="text-sm text-graphite/70">Projects API · /v2/projects</span>
        </div>

        {isLoading ? <p className="text-sm text-graphite/70">加载项目中...</p> : null}
        {error ? <p className="text-sm text-rose-700">{String((error as Error).message || "加载失败")}</p> : null}

        {!isLoading && !error && (data?.items?.length || 0) === 0 ? (
          <EmptyState title="还没有项目" description="先在后端创建项目，再在这里发起 writing run。" />
        ) : null}

        <div className="grid gap-3">
          {(data?.items || []).map((project) => (
            <article key={project.id} className="rounded-xl border border-ink/10 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-ink">{project.title}</h3>
                  <p className="mt-1 text-sm text-graphite/70">{project.genre || "未设置题材"}</p>
                </div>
                <Button asChild size="sm" variant="secondary">
                  <Link href={`/projects?project_id=${project.id}`}>
                    <PlayCircle className="mr-1.5 h-4 w-4" />
                    选择
                  </Link>
                </Button>
              </div>
              <p className="mt-3 line-clamp-2 text-sm text-graphite/75">{project.premise || "暂无前提描述"}</p>
              <p className="mt-2 text-xs text-graphite/60">ID: {project.id}</p>
            </article>
          ))}
        </div>
      </Card>

      <Card className="p-6">
        <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink">发起写作 Run</h2>
        <p className="mt-2 text-sm text-graphite/70">
          通过 BFF 触发 `/v2/projects/{"{project_id}"}/writing/runs`，随后进入实时 Run 时间线。
        </p>

        <form className="mt-5 space-y-4" onSubmit={onSubmit}>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">Project ID</span>
            <input
              {...register("project_id")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              placeholder="项目 ID"
            />
            <p className="mt-1 text-xs text-rose-700">{formState.errors.project_id?.message}</p>
          </label>

          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">Workflow Type</span>
            <select
              {...register("workflow_type")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            >
              <option value="writing_full">writing_full</option>
              <option value="chapter_generation">chapter_generation</option>
              <option value="revision">revision</option>
              <option value="consistency_review">consistency_review</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">Writing Goal</span>
            <textarea
              {...register("writing_goal")}
              className="min-h-28 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              placeholder="例如：推进主角与反派在第三章的正面冲突，保留伏笔"
            />
            <p className="mt-1 text-xs text-rose-700">{formState.errors.writing_goal?.message}</p>
          </label>

          <Button type="submit" className="w-full" disabled={formState.isSubmitting}>
            <Rocket className="mr-2 h-4 w-4" />
            {formState.isSubmitting ? "创建中..." : "创建并进入实时监控"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
