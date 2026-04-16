"use client";

import Link from "next/link";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock3,
  FileStack,
  History,
  Loader2,
  PenLine,
  PlayCircle,
  PlusCircle,
  Sparkles,
  XCircle
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { BaseSyntheticEvent } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { getProjects, type WorkflowRunDetail } from "@/generated/api/client";
import type { Project } from "@/generated/api/types";
import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { EmptyState } from "@/shared/ui/empty-state";
import { Modal } from "@/shared/ui/modal";
import { toast } from "@/shared/ui/toast";
import { StoryAssetsPanel } from "@/modules/projects/components/story-assets-panel";

const runSchema = z.object({
  project_id: z.string().min(1, "请选择项目"),
  writing_goal: z.string().min(4, "请填写写作目标"),
  workflow_type: z.string().default("writing_full"),
  target_words: z.coerce.number().int().min(300, "最少 300 字").max(10000, "最多 10000 字")
});

const projectFormSchema = z.object({
  title: z.string().min(1, "请填写项目名"),
  genre: z.string().optional(),
  premise: z.string().optional(),
  visibility: z.enum(["members", "private"]).default("members"),
  target_audience: z.string().optional(),
  tone: z.string().optional(),
  tags_text: z.string().optional()
});

const bootstrapSchema = z.object({
  outline_title: z.string().optional(),
  outline_content: z.string().optional(),
  character_lines: z.string().optional(),
  world_lines: z.string().optional(),
  timeline_lines: z.string().optional(),
  foreshadowing_lines: z.string().optional()
});

const chapterEditSchema = z.object({
  title: z.string().optional(),
  summary: z.string().optional(),
  content: z.string().optional(),
  status: z.enum(["draft", "published"]).default("draft")
});

type RunForm = z.infer<typeof runSchema>;
type ProjectForm = z.infer<typeof projectFormSchema>;
type BootstrapForm = z.infer<typeof bootstrapSchema>;
type ChapterEditForm = z.infer<typeof chapterEditSchema>;
type ProjectVisibility = "members" | "private";

type Chapter = {
  id: string;
  chapter_no: number;
  title: string | null;
  summary: string | null;
  content: string | null;
  status: string;
  draft_version: number;
  updated_at: string | null;
};

type ChapterVersion = {
  id: number;
  chapter_id: string;
  version_no: number;
  content: string | null;
  summary: string | null;
  source_agent: string | null;
  source_workflow: string | null;
  created_at: string | null;
};

type ChapterCandidate = {
  id: string;
  chapter_no: number;
  title: string | null;
  summary: string | null;
  content: string | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
};

type TimelineEvent = {
  id: string;
  chapter_no: number | null;
  event_title: string | null;
  event_desc: string | null;
  location: string | null;
  involved_characters: string[];
  created_at: string | null;
};

type RunProgress = {
  percent: number;
  stepText: string;
  tone: "info" | "warning" | "success" | "danger";
};

const STEP_LABELS: Record<string, string> = {
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
  persist_artifacts: "结果存档"
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
    "persist_artifacts"
  ],
  chapter_generation: ["chapter_generation"],
  consistency_review: ["consistency_review"],
  revision: ["writer_revision"]
};

/** 离开页面（如进入 Ops）后恢复「跟进的 run」；按 projectId 分桶，仅存 session。 */
const WATCH_RUN_STORAGE_KEY = "writeragent.workspace.watchRun.v1";

type WatchRunPayload = { runId: string; workflow: string };

type AuthMeResponse = {
  user?: {
    id?: string;
    preferences?: Record<string, unknown>;
  };
};

const PREFS_ENFORCE_WORD_COUNT_KEY = "enforce_chapter_word_count";

function readEnforceChapterWordCount(prefs: Record<string, unknown> | undefined): boolean {
  const raw = prefs?.[PREFS_ENFORCE_WORD_COUNT_KEY];
  if (raw === undefined || raw === null) return true;
  if (typeof raw === "boolean") return raw;
  if (typeof raw === "number") return raw !== 0;
  const s = String(raw).trim().toLowerCase();
  if (s === "0" || s === "false" || s === "no" || s === "off") return false;
  return true;
}

function readWatchRun(projectId: string): WatchRunPayload | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(WATCH_RUN_STORAGE_KEY);
    if (!raw) return null;
    const map = JSON.parse(raw) as Record<string, WatchRunPayload>;
    const entry = map[String(projectId).trim()];
    const runId = String(entry?.runId || "").trim();
    if (!runId) return null;
    return { runId, workflow: String(entry?.workflow || "writing_full") };
  } catch {
    return null;
  }
}

function writeWatchRun(projectId: string, payload: WatchRunPayload | null) {
  if (typeof window === "undefined") return;
  const pid = String(projectId || "").trim();
  if (!pid) return;
  try {
    const raw = sessionStorage.getItem(WATCH_RUN_STORAGE_KEY);
    const map = raw ? (JSON.parse(raw) as Record<string, WatchRunPayload>) : {};
    if (payload === null || !String(payload.runId || "").trim()) {
      delete map[pid];
    } else {
      map[pid] = { runId: String(payload.runId).trim(), workflow: String(payload.workflow || "writing_full") };
    }
    sessionStorage.setItem(WATCH_RUN_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // 配额或隐私模式：忽略
  }
}

/** 最近一条用于打开 Run Timeline 的 run（run 结束后仍会保留，避免「Run Timeline」入口消失） */
const LAST_TIMELINE_RUN_STORAGE_KEY = "writeragent.workspace.lastTimelineRun.v1";

function readLastTimelineRunId(projectId: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(LAST_TIMELINE_RUN_STORAGE_KEY);
    if (!raw) return null;
    const map = JSON.parse(raw) as Record<string, { runId?: string }>;
    const runId = String(map[String(projectId).trim()]?.runId || "").trim();
    return runId || null;
  } catch {
    return null;
  }
}

function writeLastTimelineRunId(projectId: string, runId: string | null) {
  if (typeof window === "undefined") return;
  const pid = String(projectId || "").trim();
  if (!pid) return;
  try {
    const raw = sessionStorage.getItem(LAST_TIMELINE_RUN_STORAGE_KEY);
    const map = raw ? (JSON.parse(raw) as Record<string, { runId: string }>) : {};
    const rid = String(runId || "").trim();
    if (!rid) {
      delete map[pid];
    } else {
      map[pid] = { runId: rid };
    }
    sessionStorage.setItem(LAST_TIMELINE_RUN_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // ignore
  }
}

function normalizeProjectVisibility(value: unknown): ProjectVisibility {
  return String(value || "").trim().toLowerCase() === "private" ? "private" : "members";
}

function projectVisibilityLabel(value: ProjectVisibility): string {
  return value === "private" ? "仅自己可见" : "成员可见";
}

function splitLines(value: string | undefined): string[] {
  return String(value || "")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function splitCsv(value: string | undefined): string[] {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildMetadataPayload(values: ProjectForm, base?: Record<string, unknown>): Record<string, unknown> {
  const payload: Record<string, unknown> = { ...(base || {}) };
  payload.visibility = values.visibility;

  const audience = String(values.target_audience || "").trim();
  const tone = String(values.tone || "").trim();
  const tags = splitCsv(values.tags_text);

  if (audience) payload.target_audience = audience;
  else delete payload.target_audience;

  if (tone) payload.tone = tone;
  else delete payload.tone;

  if (tags.length > 0) payload.tags = tags;
  else delete payload.tags;

  return payload;
}

function metadataToForm(metadata: Record<string, unknown> | null | undefined): Pick<ProjectForm, "visibility" | "target_audience" | "tone" | "tags_text"> {
  const source = metadata || {};
  const tags = Array.isArray(source.tags) ? source.tags.map((item) => String(item).trim()).filter(Boolean) : [];
  return {
    visibility: normalizeProjectVisibility(source.visibility),
    target_audience: String(source.target_audience || "").trim(),
    tone: String(source.tone || "").trim(),
    tags_text: tags.join(", ")
  };
}

function chapterStatusLabel(status: string): string {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "published") return "已发布";
  if (normalized === "draft") return "草稿";
  return normalized || "未知";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return value;
  return new Date(ts).toLocaleString();
}

function isPromptEchoText(value: string | null | undefined): boolean {
  const text = String(value || "").trim();
  if (!text) return false;
  return text.includes("{\"project\"") || text.includes("\"story_constraints\"");
}

function sanitizeContentField(raw: string | null | undefined): string {
  const text = String(raw || "").trim();
  if (!text) return "";
  if (!text.startsWith("{")) return text;
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed !== "object" || parsed === null) return text;
    const paths: string[][] = [
      ["chapter", "content"],
      ["content"],
      ["chapter", "summary"],
      ["summary"],
      ["chapter", "title"],
      ["title"],
    ];
    for (const path of paths) {
      let node: unknown = parsed;
      for (const key of path) {
        if (node && typeof node === "object" && key in (node as Record<string, unknown>)) {
          node = (node as Record<string, unknown>)[key];
        } else {
          node = undefined;
          break;
        }
      }
      if (typeof node === "string" && node.trim().length > 10 && !node.trim().startsWith("{")) {
        return node.trim();
      }
    }
  } catch {
    // not JSON
  }
  return text;
}

function stepLabel(stepKey: string): string {
  const normalized = String(stepKey || "").trim().toLowerCase();
  if (!normalized) return "未命名步骤";
  return STEP_LABELS[normalized] || normalized.replace(/_/g, " ");
}

/** 兼容 API / ORM 枚举序列化，例如 workflowstepstatus.running → running */
function normalizeWorkflowStepStatus(raw: unknown): string {
  const s = String(raw || "").trim().toLowerCase();
  if (!s) return "";
  const tail = s.includes(".") ? (s.split(".").pop() || s).trim() : s;
  return tail;
}

function computeRunProgress(run: WorkflowRunDetail | undefined, workflowType: string): RunProgress {
  if (!run) {
    return { percent: 0, stepText: "尚未开始", tone: "info" };
  }
  const status = String(run.status || "").toLowerCase();
  const steps = [...(run.steps || [])].sort((a, b) => Number(a.id) - Number(b.id));
  const byKey = new Map<string, string>();
  for (const step of steps) {
    byKey.set(String(step.step_key || "").toLowerCase(), normalizeWorkflowStepStatus(step.status));
  }

  const template = WORKFLOW_STEP_TEMPLATES[String(workflowType || "").toLowerCase()] || [];
  const effectiveOrder = template.length > 0 ? template : steps.map((item) => String(item.step_key || "").toLowerCase());
  const uniqueOrder = Array.from(new Set(effectiveOrder.filter(Boolean)));
  const total = uniqueOrder.length || Math.max(1, steps.length);

  // Run 已 claim 为 running 后，Planner 会先调 LLM 再写入 steps；此窗口内 steps 为空，不应显示「排队中」。
  if (steps.length === 0 && status === "running") {
    const pct = Math.max(10, Math.min(22, Math.round(100 / Math.max(total, 5))));
    return {
      percent: pct,
      stepText: "执行中：Planner 正在生成步骤计划（步骤列表即将出现）",
      tone: "info"
    };
  }

  const completed = uniqueOrder.filter((key) => {
    const itemStatus = byKey.get(key);
    return itemStatus === "success" || itemStatus === "skipped";
  }).length;

  const runningStep = steps.find((item) => normalizeWorkflowStepStatus(item.status) === "running");
  const pendingStep = steps.find((item) => {
    const normalized = normalizeWorkflowStepStatus(item.status);
    return normalized === "pending" || normalized === "queued";
  });

  if (status === "waiting_review") {
    return {
      percent: Math.max(88, Math.round((completed / total) * 100)),
      stepText: "等待你审核候选稿",
      tone: "warning"
    };
  }
  if (status === "success") {
    return { percent: 100, stepText: "已完成", tone: "success" };
  }
  if (status === "failed" || status === "cancelled") {
    return {
      percent: Math.max(10, Math.round((completed / total) * 100)),
      stepText: run.error_message || "运行失败",
      tone: "danger"
    };
  }

  const currentStepKey = String((runningStep?.step_key || pendingStep?.step_key || "") as string).trim();
  const percent = Math.max(5, Math.min(95, Math.round((completed / total) * 100)));
  return {
    percent,
    stepText: currentStepKey ? `当前步骤：${stepLabel(currentStepKey)} (${currentStepKey})` : "排队中，等待调度",
    tone: status === "queued" ? "warning" : "info"
  };
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers || {})
    }
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(String((body as { detail?: unknown }).detail || "请求失败"));
  return body as T;
}

function parseCharacterLines(input: string | undefined): Array<Record<string, unknown>> {
  return splitLines(input).map((line) => {
    const [name, roleType, faction, ageRaw] = line.split("|").map((item) => item.trim());
    const age = Number(ageRaw || "");
    return {
      name: name || line.trim(),
      role_type: roleType || null,
      faction: faction || null,
      age: Number.isFinite(age) && age > 0 ? Math.floor(age) : null,
      profile_json: {},
      speech_style_json: {},
      arc_status_json: {},
      is_canonical: true
    };
  });
}

function parseWorldLines(input: string | undefined): Array<Record<string, unknown>> {
  return splitLines(input).map((line) => {
    const [title, entryType, content] = line.split("|").map((item) => item.trim());
    return {
      title: title || line.trim(),
      entry_type: entryType || null,
      content: content || null,
      metadata_json: {},
      is_canonical: true
    };
  });
}

function parseTimelineLines(input: string | undefined): Array<Record<string, unknown>> {
  return splitLines(input).map((line) => {
    const [chapterRaw, eventTitle, eventDesc, location, charactersCsv] = line.split("|").map((item) => item.trim());
    const chapterNo = Number(chapterRaw || "");
    return {
      chapter_no: Number.isFinite(chapterNo) && chapterNo > 0 ? Math.floor(chapterNo) : null,
      event_title: eventTitle || line.trim(),
      event_desc: eventDesc || null,
      location: location || null,
      involved_characters: splitCsv(charactersCsv),
      causal_links: []
    };
  });
}

function parseForeshadowingLines(input: string | undefined): Array<Record<string, unknown>> {
  return splitLines(input).map((line) => {
    const [setupChapterRaw, setupText, expectedPayoff, payoffChapterRaw, payoffText, statusRaw] = line
      .split("|")
      .map((item) => item.trim());
    const setupChapterNo = Number(setupChapterRaw || "");
    const payoffChapterNo = Number(payoffChapterRaw || "");
    const status = String(statusRaw || "").toLowerCase() === "resolved" ? "resolved" : "open";
    return {
      setup_chapter_no: Number.isFinite(setupChapterNo) && setupChapterNo > 0 ? Math.floor(setupChapterNo) : null,
      setup_text: setupText || line.trim(),
      expected_payoff: expectedPayoff || null,
      payoff_chapter_no: Number.isFinite(payoffChapterNo) && payoffChapterNo > 0 ? Math.floor(payoffChapterNo) : null,
      payoff_text: payoffText || null,
      status
    };
  });
}

export function ProjectWorkbench() {
  const queryClient = useQueryClient();
  const [globalMessage, setGlobalMessage] = useState<string | null>(null);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const [newProjectOpen, setNewProjectOpen] = useState(false);
  const [editProjectId, setEditProjectId] = useState<string | null>(null);
  const [bootstrapProjectId, setBootstrapProjectId] = useState<string | null>(null);
  const [chapterEditId, setChapterEditId] = useState<string | null>(null);
  const [versionChapterId, setVersionChapterId] = useState<string | null>(null);
  const [previewVersionId, setPreviewVersionId] = useState<number | null>(null);
  const [aiGenerating, setAiGenerating] = useState<Record<string, boolean>>({});

  const [writePanelOpen, setWritePanelOpen] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  /** 当前项目下最近一次创建的 run，用于 Run Timeline 入口（run 结束后仍保留） */
  const [lastTimelineRunId, setLastTimelineRunId] = useState<string | null>(null);
  const [activeRunWorkflow, setActiveRunWorkflow] = useState("writing_full");

  const { data, isLoading, error } = useQuery({ queryKey: ["projects"], queryFn: getProjects });
  const projects = data?.items || [];

  const { data: authMe } = useQuery({
    queryKey: ["auth-me"],
    queryFn: () => fetchJson<AuthMeResponse>("/api/auth/me"),
    staleTime: 60_000,
  });

  const [enforceChapterWordCount, setEnforceChapterWordCount] = useState(true);

  useEffect(() => {
    const prefs = authMe?.user?.preferences as Record<string, unknown> | undefined;
    setEnforceChapterWordCount(readEnforceChapterWordCount(prefs));
  }, [authMe?.user?.preferences]);

  const projectById = useMemo(() => {
    const map = new Map<string, Project>();
    for (const item of projects) map.set(item.id, item);
    return map;
  }, [projects]);

  const runForm = useForm<RunForm>({
    resolver: zodResolver(runSchema),
    defaultValues: {
      workflow_type: "writing_full",
      target_words: 1200,
      project_id: ""
    }
  });

  const selectedProjectId = runForm.watch("project_id");
  const selectedProject = selectedProjectId ? projectById.get(selectedProjectId) || null : null;
  const editingProject = editProjectId ? projectById.get(editProjectId) || null : null;
  const bootstrapTargetProject = bootstrapProjectId ? projectById.get(bootstrapProjectId) || null : null;

  const createProjectForm = useForm<ProjectForm>({
    resolver: zodResolver(projectFormSchema),
    defaultValues: {
      title: "",
      genre: "",
      premise: "",
      visibility: "members",
      target_audience: "",
      tone: "",
      tags_text: ""
    }
  });

  const editProjectForm = useForm<ProjectForm>({
    resolver: zodResolver(projectFormSchema),
    defaultValues: {
      title: "",
      genre: "",
      premise: "",
      visibility: "members",
      target_audience: "",
      tone: "",
      tags_text: ""
    }
  });

  const bootstrapForm = useForm<BootstrapForm>({
    resolver: zodResolver(bootstrapSchema),
    defaultValues: {
      outline_title: "",
      outline_content: "",
      character_lines: "",
      world_lines: "",
      timeline_lines: "",
      foreshadowing_lines: ""
    }
  });

  const chapterEditForm = useForm<ChapterEditForm>({
    resolver: zodResolver(chapterEditSchema),
    defaultValues: {
      title: "",
      summary: "",
      content: "",
      status: "draft"
    }
  });

  useEffect(() => {
    if (!projects.length) return;
    const current = String(runForm.getValues("project_id") || "").trim();
    if (current && projectById.has(current)) return;
    runForm.setValue("project_id", projects[0].id, { shouldDirty: false });
  }, [projectById, projects, runForm]);

  useEffect(() => {
    if (!editingProject) return;
    const metadataFields = metadataToForm(editingProject.metadata_json || {});
    editProjectForm.reset({
      title: editingProject.title || "",
      genre: editingProject.genre || "",
      premise: editingProject.premise || "",
      visibility: metadataFields.visibility,
      target_audience: metadataFields.target_audience,
      tone: metadataFields.tone,
      tags_text: metadataFields.tags_text
    });
  }, [editingProject, editProjectForm]);

  const { data: chaptersData, isLoading: chaptersLoading, refetch: refetchChapters } = useQuery<{ items: Chapter[] }>({
    queryKey: ["chapters", selectedProjectId],
    enabled: Boolean(selectedProjectId),
    queryFn: () => fetchJson(`/api/projects/${selectedProjectId}/chapters?include_content=1`),
    staleTime: 8_000
  });

  const { data: candidatesData, refetch: refetchCandidates } = useQuery<{ items: ChapterCandidate[] }>({
    queryKey: ["chapter-candidates", selectedProjectId],
    enabled: Boolean(selectedProjectId),
    queryFn: () => fetchJson(`/api/projects/${selectedProjectId}/chapter-candidates?limit=20`),
    refetchInterval: activeRunId ? 8_000 : false,
  });

  const { data: timelineData } = useQuery<{ items: TimelineEvent[] }>({
    queryKey: ["timeline-events", selectedProjectId],
    enabled: Boolean(selectedProjectId),
    queryFn: () => fetchJson(`/api/projects/${selectedProjectId}/timeline-events?limit=200`),
    staleTime: 12_000
  });

  const {
    data: activeRunData,
    isLoading: activeRunLoading,
    error: activeRunError
  } = useQuery<WorkflowRunDetail>({
    queryKey: ["active-run", activeRunId],
    enabled: Boolean(activeRunId),
    queryFn: () => fetchJson(`/api/writing/runs/${activeRunId}`),
    refetchInterval: (query) => {
      const status = String((query.state.data as WorkflowRunDetail | undefined)?.status || "").toLowerCase();
      if (!status) return 2500;
      if (["success", "failed", "cancelled"].includes(status)) return false;
      return 2500;
    }
  });

  const { data: versionsData, isLoading: versionsLoading, refetch: refetchVersions } = useQuery<{ items: ChapterVersion[] }>({
    queryKey: ["chapter-versions", selectedProjectId, versionChapterId],
    enabled: Boolean(selectedProjectId && versionChapterId),
    queryFn: () => fetchJson(`/api/projects/${selectedProjectId}/chapters/${versionChapterId}/versions`),
    staleTime: 0
  });

  const selectedChapter = useMemo(() => {
    if (!chapterEditId) return null;
    return (chaptersData?.items || []).find((item) => item.id === chapterEditId) || null;
  }, [chapterEditId, chaptersData?.items]);

  const { data: chapterModalCharacters } = useQuery<{
    items: { id: string; name: string; role_type: string | null }[];
  }>({
    queryKey: ["characters", selectedProjectId, "chapter-modal"],
    enabled: Boolean(selectedProjectId && chapterEditId),
    queryFn: () => fetchJson(`/api/projects/${selectedProjectId}/characters`),
    staleTime: 10_000,
  });

  const chapterModalProtagonist = useMemo(() => {
    const items = chapterModalCharacters?.items || [];
    return (
      items.find((c) => String(c.role_type || "").toLowerCase() === "protagonist") ||
      items[0] ||
      null
    );
  }, [chapterModalCharacters?.items]);

  const { data: chapterModalAssetSnap } = useQuery<{
    inventory_json: Record<string, unknown>;
    wealth_json: Record<string, unknown>;
    has_snapshot: boolean;
  }>({
    queryKey: [
      "character-chapter-assets",
      selectedProjectId,
      chapterModalProtagonist?.id,
      selectedChapter?.chapter_no,
    ],
    enabled: Boolean(selectedProjectId && chapterModalProtagonist && selectedChapter),
    queryFn: () =>
      fetchJson(
        `/api/projects/${selectedProjectId}/characters/${chapterModalProtagonist!.id}/chapter-assets?chapter_no=${selectedChapter!.chapter_no}`,
      ),
    staleTime: 8_000,
  });

  const previewVersion = useMemo(() => {
    if (previewVersionId === null) return null;
    return (versionsData?.items || []).find((item) => item.id === previewVersionId) || null;
  }, [previewVersionId, versionsData?.items]);

  useEffect(() => {
    if (!selectedChapter) return;
    chapterEditForm.reset({
      title: selectedChapter.title || "",
      summary: selectedChapter.summary || "",
      content: selectedChapter.content || "",
      status: String(selectedChapter.status || "draft").toLowerCase() === "published" ? "published" : "draft"
    });
  }, [selectedChapter, chapterEditForm]);

  const runProgress = useMemo(() => {
    if (activeRunId && activeRunLoading && !activeRunData) {
      return { percent: 6, stepText: "Run 已创建，正在获取状态…", tone: "info" as const };
    }
    if (activeRunId && activeRunError && !activeRunData) {
      return { percent: 6, stepText: `状态获取失败：${String((activeRunError as Error)?.message || "请重试")}`, tone: "danger" as const };
    }
    if (activeRunId && !activeRunData) {
      return { percent: 6, stepText: "Run 已创建，等待调度…", tone: "warning" as const };
    }
    return computeRunProgress(activeRunData, activeRunWorkflow);
  }, [activeRunData, activeRunError, activeRunId, activeRunLoading, activeRunWorkflow]);
  const runQueuedTooLong = useMemo(() => {
    if (!activeRunData) return null;
    const status = String(activeRunData.status || "").toLowerCase();
    if (status !== "queued") return null;
    if ((activeRunData.steps || []).length > 0) return null;
    const createdAt = Date.parse(String(activeRunData.created_at || ""));
    if (!Number.isFinite(createdAt)) return null;
    const elapsedMs = Date.now() - createdAt;
    if (elapsedMs < 15_000) return null;
    return Math.floor(elapsedMs / 1000);
  }, [activeRunData]);

  // 从 Ops 等路由返回时恢复跟进的 run；切换项目时按项目读取/清空。
  useEffect(() => {
    if (!selectedProjectId) {
      setActiveRunId(null);
      setLastTimelineRunId(null);
      return;
    }
    const savedTimeline = readLastTimelineRunId(selectedProjectId);
    setLastTimelineRunId(savedTimeline);
    const saved = readWatchRun(selectedProjectId);
    if (saved) {
      setActiveRunId(saved.runId);
      setActiveRunWorkflow(saved.workflow);
      writeLastTimelineRunId(selectedProjectId, saved.runId);
      setLastTimelineRunId(saved.runId);
    } else {
      setActiveRunId(null);
    }
  }, [selectedProjectId]);

  useEffect(() => {
    if (!activeRunData || !selectedProjectId || !activeRunId) return;
    if (String(activeRunData.project_id) !== String(selectedProjectId)) {
      writeWatchRun(selectedProjectId, null);
      setActiveRunId(null);
    }
  }, [activeRunData, activeRunId, selectedProjectId]);

  useEffect(() => {
    if (!activeRunData || !selectedProjectId) return;
    const st = String(activeRunData.status || "").toLowerCase();
    if (!["success", "failed", "cancelled"].includes(st)) return;
    writeWatchRun(selectedProjectId, null);
    setActiveRunId(null);
  }, [activeRunData, selectedProjectId]);

  const timelineItems = useMemo(() => {
    const rows = [...(timelineData?.items || [])];
    rows.sort((a, b) => {
      const chapterA = a.chapter_no ?? 9999;
      const chapterB = b.chapter_no ?? 9999;
      if (chapterA !== chapterB) return chapterA - chapterB;
      return Date.parse(String(a.created_at || "")) - Date.parse(String(b.created_at || ""));
    });
    return rows;
  }, [timelineData?.items]);

  const pendingCandidates = useMemo(
    () => (candidatesData?.items || []).filter((item) => String(item.status || "").toLowerCase() === "pending"),
    [candidatesData?.items]
  );

  const withErrorBoundary =
    (action: (event?: BaseSyntheticEvent) => Promise<void>) => async (event?: BaseSyntheticEvent) => {
      try {
        setGlobalError(null);
        setGlobalMessage(null);
        await action(event);
      } catch (err) {
        const msg = String((err as Error)?.message || "操作失败");
        setGlobalError(msg);
        toast.error(msg);
      }
    };

  const createRun = runForm.handleSubmit(async (values) => {
    const hasChapters = (chaptersData?.items || []).length > 0;
    const hasCandidates = (candidatesData?.items || []).length > 0;
    if (!hasChapters && !hasCandidates) {
      let hasAssets = false;
      try {
        const chars = await fetchJson<{ items: unknown[] }>(`/api/projects/${values.project_id}/characters`);
        if (chars.items.length > 0) hasAssets = true;
      } catch { /* ignore */ }
      if (!hasAssets) {
        toast.warning("该项目尚未初始化故事资产（大纲/角色等），建议先点击「初始化」按钮完善基础设定。");
        setBootstrapProjectId(values.project_id);
        return;
      }
    }
    const body = await fetchJson<{ run_id: string; status: string }>("/api/writing/runs", {
      method: "POST",
      body: JSON.stringify({
        project_id: values.project_id,
        workflow_type: values.workflow_type,
        writing_goal: values.writing_goal,
        target_words: values.target_words,
        enforce_chapter_word_count: enforceChapterWordCount
      })
    });
    const newRunId = String(body.run_id || "").trim() || null;
    setActiveRunId(newRunId);
    setActiveRunWorkflow(values.workflow_type);
    if (newRunId) {
      writeWatchRun(values.project_id, { runId: newRunId, workflow: values.workflow_type });
      writeLastTimelineRunId(values.project_id, newRunId);
      if (String(values.project_id) === String(selectedProjectId)) {
        setLastTimelineRunId(newRunId);
      }
    }
    setWritePanelOpen(true);
    setGlobalMessage(`Run 已创建：${body.run_id}`);
    await Promise.all([refetchCandidates(), refetchChapters()]);
  });

  const createProject = createProjectForm.handleSubmit(async (values) => {
    const metadata = buildMetadataPayload(values);
    const body = await fetchJson<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify({
        title: values.title,
        genre: values.genre || null,
        premise: values.premise || null,
        metadata_json: metadata
      })
    });
    await queryClient.invalidateQueries({ queryKey: ["projects"] });
    runForm.setValue("project_id", body.id, { shouldDirty: true });
    setNewProjectOpen(false);
    createProjectForm.reset({
      title: "",
      genre: "",
      premise: "",
      visibility: "members",
      target_audience: "",
      tone: "",
      tags_text: ""
    });
    setGlobalMessage("项目已创建。你可以继续初始化资产或直接开始写作。");
  });

  const updateProject = editProjectForm.handleSubmit(async (values) => {
    if (!editingProject) throw new Error("请先选择项目");
    const metadata = buildMetadataPayload(values, editingProject.metadata_json || {});
    await fetchJson(`/api/projects/${editingProject.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: values.title,
        genre: values.genre || null,
        premise: values.premise || null,
        metadata_json: metadata
      })
    });
    await queryClient.invalidateQueries({ queryKey: ["projects"] });
    setEditProjectId(null);
    setGlobalMessage("项目设置已保存。");
  });

  const aiGenerateAsset = async (assetType: string) => {
    if (!bootstrapTargetProject) return;
    setAiGenerating((prev) => ({ ...prev, [assetType]: true }));
    try {
      const result = await fetchJson<{
        ok: boolean;
        data: Record<string, unknown>;
        text: string;
        is_mock: boolean;
      }>(`/api/projects/${bootstrapTargetProject.id}/ai-generate-asset`, {
        method: "POST",
        body: JSON.stringify({
          asset_type: assetType,
          premise: bootstrapTargetProject.premise || "",
          genre: bootstrapTargetProject.genre || "",
          title: bootstrapTargetProject.title || "",
          tone: String((bootstrapTargetProject as unknown as Record<string, unknown>).tone || ""),
          target_audience: String(
            (bootstrapTargetProject as unknown as Record<string, unknown>).target_audience || "",
          ),
        })
      });
      const d = result.data || {};
      const txt = result.text || "";

      if (assetType === "outline") {
        const title = String(d.title || "").trim();
        let content = String(d.content || "").trim();
        const promise = String(d.promise || "").trim();
        const question = String(d.central_question || "").trim();
        if (promise || question) {
          const meta = [promise ? `核心承诺：${promise}` : "", question ? `核心悬念：${question}` : ""].filter(Boolean).join("\n");
          content = content ? `${meta}\n\n${content}` : meta;
        }
        if (title) bootstrapForm.setValue("outline_title", title);
        if (content) bootstrapForm.setValue("outline_content", content);
        if (!title && !content && txt) bootstrapForm.setValue("outline_content", txt);
      } else if (assetType === "characters") {
        const chars = (d.characters || []) as Array<Record<string, unknown>>;
        if (chars.length > 0) {
          bootstrapForm.setValue(
            "character_lines",
            chars.map((c) => `${c.name || ""}|${c.role_type || "supporting"}|${c.faction || ""}|${c.age || ""}`).join("\n")
          );
        } else if (txt) bootstrapForm.setValue("character_lines", txt);
      } else if (assetType === "world_entries") {
        const entries = (d.entries || []) as Array<Record<string, unknown>>;
        if (entries.length > 0) {
          bootstrapForm.setValue(
            "world_lines",
            entries.map((e) => `${e.title || ""}|${e.entry_type || "rule"}|${e.content || ""}`).join("\n")
          );
        } else if (txt) bootstrapForm.setValue("world_lines", txt);
      } else if (assetType === "timeline") {
        const events = (d.events || []) as Array<Record<string, unknown>>;
        if (events.length > 0) {
          bootstrapForm.setValue(
            "timeline_lines",
            events.map((e) => `${e.chapter_no || ""}|${e.title || ""}|${e.description || ""}|${e.location || ""}|${e.characters_involved || ""}`).join("\n")
          );
        } else if (txt) bootstrapForm.setValue("timeline_lines", txt);
      } else if (assetType === "foreshadowing") {
        const items = (d.items || []) as Array<Record<string, unknown>>;
        if (items.length > 0) {
          bootstrapForm.setValue(
            "foreshadowing_lines",
            items.map((f) => `${f.planted_chapter || ""}|${f.planted_content || ""}|${f.expected_payoff || ""}|${f.payoff_chapter || ""}||open`).join("\n")
          );
        } else if (txt) bootstrapForm.setValue("foreshadowing_lines", txt);
      }
      toast.success(`${assetType} AI 生成完成${result.is_mock ? "（Mock 模式）" : ""}，请按需修改。`);
    } catch (err) {
      toast.error(`AI 生成失败：${err instanceof Error ? err.message : "未知错误"}`);
    } finally {
      setAiGenerating((prev) => ({ ...prev, [assetType]: false }));
    }
  };

  const submitBootstrapProject = bootstrapForm.handleSubmit(async (values) => {
    if (!bootstrapTargetProject) throw new Error("未选择项目");
    const payload = {
      outline:
        String(values.outline_title || "").trim() || String(values.outline_content || "").trim()
          ? {
              title: String(values.outline_title || "").trim() || null,
              content: String(values.outline_content || "").trim() || null,
              structure_json: {},
              set_active: true
            }
          : null,
      characters: parseCharacterLines(values.character_lines),
      world_entries: parseWorldLines(values.world_lines),
      timeline_events: parseTimelineLines(values.timeline_lines),
      foreshadowings: parseForeshadowingLines(values.foreshadowing_lines)
    };

    const isEmpty =
      payload.outline === null &&
      payload.characters.length === 0 &&
      payload.world_entries.length === 0 &&
      payload.timeline_events.length === 0 &&
      payload.foreshadowings.length === 0;

    if (isEmpty) throw new Error("请至少填写一项初始化信息");

    await fetchJson(`/api/projects/${bootstrapTargetProject.id}/bootstrap`, {
      method: "POST",
      body: JSON.stringify(payload)
    });

    bootstrapForm.reset();
    setBootstrapProjectId(null);
    const pid = bootstrapTargetProject.id;
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["projects"] }),
      queryClient.invalidateQueries({ queryKey: ["outline", pid] }),
      queryClient.invalidateQueries({ queryKey: ["characters", pid] }),
      queryClient.invalidateQueries({ queryKey: ["world-entries", pid] }),
      queryClient.invalidateQueries({ queryKey: ["timeline-events-asset", pid] }),
      refetchChapters(),
      refetchCandidates()
    ]);
    setGlobalMessage("项目初始化完成，已导入基础资产。");
  });

  const saveChapter = chapterEditForm.handleSubmit(async (values) => {
    if (!selectedProjectId || !selectedChapter) throw new Error("请先选择章节");
    await fetchJson(`/api/projects/${selectedProjectId}/chapters/${selectedChapter.id}`, {
      method: "PATCH",
      body: JSON.stringify({
        title: values.title || null,
        summary: values.summary || null,
        content: values.content || null,
        status: values.status
      })
    });
    await Promise.all([refetchChapters(), refetchVersions()]);
    setChapterEditId(null);
    setGlobalMessage(`第 ${selectedChapter.chapter_no} 章已保存，并生成新版本。`);
  });

  const rollbackChapter = async (chapterId: string, versionNo: number) => {
    if (!selectedProjectId) throw new Error("请先选择项目");
    await fetchJson(`/api/projects/${selectedProjectId}/chapters/${chapterId}/rollback/${versionNo}`, {
      method: "POST"
    });
    await Promise.all([refetchChapters(), refetchVersions()]);
    setGlobalMessage(`已回滚到版本 v${versionNo}。`);
  };

  const approveCandidate = async (candidateId: string) => {
    if (!selectedProjectId) throw new Error("请先选择项目");
    await fetchJson(`/api/projects/${selectedProjectId}/chapter-candidates/${candidateId}/approve`, {
      method: "POST"
    });
    await Promise.all([refetchCandidates(), refetchChapters()]);
    setGlobalMessage("候选稿已通过并落库。run 将继续推进。\n");
  };

  const rejectCandidate = async (candidateId: string) => {
    if (!selectedProjectId) throw new Error("请先选择项目");
    await fetchJson(`/api/projects/${selectedProjectId}/chapter-candidates/${candidateId}/reject`, {
      method: "POST",
      body: JSON.stringify({ cancel_run: false })
    });
    await refetchCandidates();
    setGlobalMessage("候选稿已拒绝，run 仍保持 waiting_review，等待下一次处理。\n");
  };

  const deleteProject = async (projectId: string) => {
    await fetchJson(`/api/projects/${projectId}`, { method: "DELETE" });
    await queryClient.invalidateQueries({ queryKey: ["projects"] });
    writeWatchRun(projectId, null);
    writeLastTimelineRunId(projectId, null);
    if (selectedProjectId === projectId) {
      runForm.setValue("project_id", "");
      setActiveRunId(null);
      setLastTimelineRunId(null);
    }
    toast.success("项目已删除");
  };

  const deleteChapter = async (chapterId: string) => {
    if (!selectedProjectId) throw new Error("请先选择项目");
    await fetchJson(`/api/projects/${selectedProjectId}/chapters/${chapterId}`, { method: "DELETE" });
    await refetchChapters();
    toast.success("章节已删除");
  };

  return (
    <div className="space-y-6">
      <Card className="p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="font-[var(--font-display)] text-3xl font-semibold text-ink">项目工作台</h1>
            <p className="mt-1 text-sm text-graphite/75">项目、写作、审阅、章节版本与故事时间线在同一页面闭环。</p>
          </div>
          <div className="flex items-center gap-2">
            <Button type="button" variant="secondary" onClick={() => setWritePanelOpen((prev) => !prev)}>
              {writePanelOpen ? <ChevronUp className="mr-1.5 h-4 w-4" /> : <ChevronDown className="mr-1.5 h-4 w-4" />}
              开始写作
            </Button>
            <Button type="button" onClick={() => setNewProjectOpen(true)}>
              <PlusCircle className="mr-1.5 h-4 w-4" />
              新建项目
            </Button>
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <Card className="p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink">项目列表</h2>
            <span className="text-sm text-graphite/70">点击“初始化”可弹窗补全资产</span>
          </div>

          {isLoading ? <p className="text-sm text-graphite/70">加载项目中...</p> : null}
          {error ? <p className="text-sm text-rose-700">{String((error as Error).message || "加载失败")}</p> : null}

          {!isLoading && !error && projects.length === 0 ? (
            <EmptyState title="还没有项目" description="先点击右上角“新建项目”，再开始第一章创作。" />
          ) : null}

          <div className="max-h-[560px] space-y-3 overflow-y-auto pr-1">
            {projects.map((project) => {
              const active = selectedProjectId === project.id;
              const visibility = normalizeProjectVisibility((project.metadata_json || {}).visibility);
              return (
                <article
                  key={project.id}
                  className={`rounded-2xl border bg-white p-4 transition-all ${active ? "border-surge/50 ring-2 ring-surge/20" : "border-ink/10"}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className="text-xl font-semibold text-ink">{project.title}</h3>
                      <p className="mt-1 text-sm text-graphite/70">{project.genre || "未设置题材"}</p>
                      <p className="mt-1 text-xs text-graphite/60">{projectVisibilityLabel(visibility)}</p>
                    </div>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        variant={active ? "primary" : "secondary"}
                        type="button"
                        onClick={() => runForm.setValue("project_id", project.id, { shouldDirty: true })}
                      >
                        <PlayCircle className="mr-1.5 h-4 w-4" />
                        {active ? "已选择" : "选择"}
                      </Button>
                      <Button size="sm" variant="secondary" type="button" onClick={() => setBootstrapProjectId(project.id)}>
                        <Sparkles className="mr-1.5 h-4 w-4" />初始化
                      </Button>
                    </div>
                  </div>
                  <p className="mt-3 line-clamp-2 text-sm text-graphite/80">{project.premise || "暂无前提描述"}</p>
                  <div className="mt-3 flex justify-end gap-2">
                    <Button size="sm" variant="ghost" type="button" onClick={() => setEditProjectId(project.id)}>
                      项目设置
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      type="button"
                      className="text-rose-600 hover:text-rose-700 hover:bg-rose-50"
                      onClick={() => {
                        if (window.confirm(`确定删除项目「${project.title}」？此操作不可恢复。`)) {
                          withErrorBoundary(() => deleteProject(project.id))();
                        }
                      }}
                    >
                      <XCircle className="mr-1 h-3.5 w-3.5" />删除
                    </Button>
                  </div>
                </article>
              );
            })}
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink">发起写作 Run</h2>
            <Button variant="ghost" size="sm" type="button" onClick={() => setWritePanelOpen((prev) => !prev)}>
              {writePanelOpen ? "收起" : "展开"}
            </Button>
          </div>
          <p className="mt-1 text-sm text-graphite/70">
            收起表单后仍会显示进行中的 run 进度；从 Ops 等页面返回本会话内会自动恢复跟进的 run。
          </p>

          {(runForm.formState.isSubmitting || activeRunId || lastTimelineRunId) && (
            <div className="mt-4 rounded-xl border border-ink/10 bg-white/80 p-3">
              {runForm.formState.isSubmitting || activeRunId ? (
                <>
                  <div className="mb-2 flex items-center justify-between text-xs text-graphite/70">
                    <span>{runProgress.stepText}</span>
                    <span>{runProgress.percent}%</span>
                  </div>
                  <div className="h-2.5 overflow-hidden rounded-full bg-slate-200/80">
                    <div
                      className={`h-full rounded-full bg-gradient-to-r transition-all duration-500 ${
                        runProgress.tone === "danger"
                          ? "from-rose-500 via-rose-400 to-amber-300"
                          : runProgress.tone === "success"
                            ? "from-emerald-500 via-teal-400 to-cyan-300"
                            : runProgress.tone === "warning"
                              ? "from-amber-500 via-orange-400 to-yellow-300"
                              : "from-ocean via-surge to-emerald-300"
                      }`}
                      style={{ width: `${runProgress.percent}%` }}
                    />
                  </div>
                </>
              ) : (
                <p className="text-xs text-graphite/70">
                  当前没有在跟进的 Run；仍可通过下方链接查看本会话内最近一次创建的时间线。
                </p>
              )}
              {lastTimelineRunId || activeRunId ? (
                <p className="mt-2 text-xs text-graphite/60">
                  {activeRunId ? <>run_id: {activeRunId}</> : <>最近 run: {lastTimelineRunId}</>}
                  <Link
                    className="ml-2 text-ocean underline underline-offset-2"
                    href={`/runs/${lastTimelineRunId || activeRunId}`}
                  >
                    查看完整时间线
                  </Link>
                </p>
              ) : null}
              {runQueuedTooLong ? (
                <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-800">
                  当前 run 已排队 {runQueuedTooLong}s，通常表示 worker 未启动。
                  <p className="mt-1 font-mono text-[11px] text-amber-900">./venv/bin/python scripts/run_orchestrator_worker.py</p>
                </div>
              ) : null}
            </div>
          )}

          {writePanelOpen ? (
            <form className="mt-4 space-y-4" onSubmit={withErrorBoundary(createRun)}>
              <label className="block">
                <span className="mb-1 block text-sm font-medium text-graphite">项目</span>
                <select
                  {...runForm.register("project_id")}
                  className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
                  disabled={projects.length === 0}
                >
                  <option value="">请选择项目</option>
                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.title} {project.genre ? `· ${project.genre}` : ""}
                    </option>
                  ))}
                </select>
                <p className="mt-1 text-xs text-rose-700">{runForm.formState.errors.project_id?.message}</p>
              </label>

              <fieldset className="block">
                <legend className="mb-1 block text-sm font-medium text-graphite">Workflow 类型</legend>
                <select
                  {...runForm.register("workflow_type")}
                  className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
                >
                  <option value="writing_full">完整写作</option>
                  <option value="chapter_generation">快速生成章节</option>
                  <option value="revision">修订润色</option>
                  <option value="consistency_review">一致性审校</option>
                </select>
                {(() => {
                  const wt = runForm.watch("workflow_type");
                  const desc: Record<string, string> = {
                    writing_full: "端到端全链路：规划 → 检索上下文 → 大纲 → 情节/角色/世界观/风格对齐 → 草稿 → 一致性审校 → 修订润色 → 存档。适合从零开始写新章节。",
                    chapter_generation: "跳过规划与对齐步骤，直接基于已有大纲与上下文生成章节正文。适合大纲已确定后的快速出稿。",
                    revision: "对已有章节正文进行修订润色，根据一致性审校报告修复风格/逻辑问题。需要先有草稿。",
                    consistency_review: "仅执行一致性审校，检查角色行为、世界观规则、时间线、伏笔是否前后矛盾，输出审校报告但不修改正文。",
                  };
                  return desc[wt] ? (
                    <p className="mt-1.5 rounded-lg bg-sky-50 px-2.5 py-1.5 text-xs text-sky-800">{desc[wt]}</p>
                  ) : null;
                })()}
              </fieldset>

              <label className="block">
                <span className="mb-1 block text-sm font-medium text-graphite">目标字数</span>
                <input
                  type="number"
                  {...runForm.register("target_words", { valueAsNumber: true })}
                  className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
                  min={200}
                  max={12000}
                />
                <p className="mt-1 text-xs text-rose-700">{runForm.formState.errors.target_words?.message}</p>
              </label>

              <div className="rounded-xl border border-ink/15 bg-white px-3 py-3">
                <label className="flex cursor-pointer items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1 h-4 w-4 shrink-0 rounded border-ink/30 text-ocean focus:ring-surge/50"
                    checked={enforceChapterWordCount}
                    onChange={async (e) => {
                      const next = e.target.checked;
                      setEnforceChapterWordCount(next);
                      try {
                        await fetchJson("/api/auth/me/preferences", {
                          method: "PATCH",
                          body: JSON.stringify({
                            preferences: { [PREFS_ENFORCE_WORD_COUNT_KEY]: next }
                          })
                        });
                        await queryClient.invalidateQueries({ queryKey: ["auth-me"] });
                        toast.success(next ? "已开启正文字数校验" : "已关闭正文字数校验（目标字数仍会传给模型）");
                      } catch (err) {
                        setEnforceChapterWordCount(!next);
                        toast.error(String((err as Error)?.message || "保存失败"));
                      }
                    }}
                    disabled={!authMe?.user?.id}
                  />
                  <span>
                    <span className="block text-sm font-medium text-graphite">校验生成正文字数</span>
                    <span className="mt-0.5 block text-xs text-graphite/70">
                      开启时要求正文有效字数落在目标字数 ±10%，否则自动重试；关闭时仍填写目标字数供模型参考，但不因长度不达标而重试。设置已保存到账号。
                    </span>
                  </span>
                </label>
              </div>

              <label className="block">
                <span className="mb-1 block text-sm font-medium text-graphite">写作目标</span>
                <textarea
                  {...runForm.register("writing_goal")}
                  className="min-h-28 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
                  placeholder="例如：第一章主角获得能力，埋下导师真实身份伏笔"
                />
                <p className="mt-1 text-xs text-rose-700">{runForm.formState.errors.writing_goal?.message}</p>
              </label>

              <Button type="submit" className="w-full" disabled={runForm.formState.isSubmitting || projects.length === 0}>
                {runForm.formState.isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />创建中...
                  </>
                ) : (
                  <>
                    <PlayCircle className="mr-2 h-4 w-4" />创建并开始写作
                  </>
                )}
              </Button>
            </form>
          ) : (
            <div className="mt-6 rounded-xl border border-dashed border-ink/20 bg-white/70 p-4 text-sm text-graphite/70">
              点击“开始写作”展开面板。
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <Card className="p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink">章节与版本</h2>
            <span className="text-sm text-graphite/70">支持编辑、版本查看与回滚</span>
          </div>

          {!selectedProjectId ? (
            <EmptyState title="请先选择项目" description="左侧选择项目后，这里会显示章节列表。" />
          ) : chaptersLoading ? (
            <p className="text-sm text-graphite/70">章节加载中...</p>
          ) : (chaptersData?.items || []).length === 0 ? (
            <EmptyState title="暂无章节" description="通过写作 run 审核通过后会生成章节。" />
          ) : (
            <div className="max-h-[520px] space-y-3 overflow-auto pr-1">
              {(chaptersData?.items || []).map((chapter) => (
                <article key={chapter.id} className="rounded-xl border border-ink/10 bg-white p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm text-graphite/65">第 {chapter.chapter_no} 章</p>
                      <h3 className="text-lg font-semibold text-ink">{chapter.title || `第 ${chapter.chapter_no} 章`}</h3>
                      <p className="mt-1 text-xs text-graphite/60">
                        {chapterStatusLabel(chapter.status)} · 版本 v{chapter.draft_version} · 更新于 {formatDate(chapter.updated_at)}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" variant="secondary" type="button" onClick={() => setChapterEditId(chapter.id)}>
                        <PenLine className="mr-1.5 h-4 w-4" />编辑
                      </Button>
                      <Button size="sm" variant="ghost" type="button" onClick={() => setVersionChapterId(chapter.id)}>
                        <History className="mr-1.5 h-4 w-4" />版本
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        type="button"
                        className="text-rose-600 hover:text-rose-700 hover:bg-rose-50"
                        onClick={() => {
                          if (window.confirm(`确定删除第 ${chapter.chapter_no} 章「${chapter.title || ""}」？`)) {
                            withErrorBoundary(() => deleteChapter(chapter.id))();
                          }
                        }}
                      >
                        <XCircle className="mr-1 h-3.5 w-3.5" />删除
                      </Button>
                    </div>
                  </div>
                  <p className="mt-3 line-clamp-3 text-sm text-graphite/80">{chapter.summary || chapter.content || "暂无内容"}</p>
                </article>
              ))}
            </div>
          )}
        </Card>

        <Card className="p-6">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink">候选稿审阅</h2>
            <span className="text-sm text-graphite/70">先审后存</span>
          </div>

          {!selectedProjectId ? (
            <EmptyState title="请先选择项目" description="选择项目后这里会显示待审候选稿。" />
          ) : pendingCandidates.length === 0 ? (
            <div className="rounded-xl border border-dashed border-ink/20 bg-white/60 p-4 text-sm text-graphite/70">
              当前没有待审候选稿。
            </div>
          ) : (
            <div className="max-h-[520px] space-y-3 overflow-auto pr-1">
              {pendingCandidates.map((candidate) => (
                <article key={candidate.id} className="rounded-xl border border-amber-200 bg-amber-50/65 p-4">
                  <p className="text-xs text-amber-900/70">候选 · 第 {candidate.chapter_no} 章</p>
                  <h3 className="mt-1 text-lg font-semibold text-ink">{candidate.title || "未命名候选稿"}</h3>
                  {isPromptEchoText(candidate.title) || isPromptEchoText(candidate.summary) ? (
                    <p className="mt-2 rounded-lg border border-amber-300 bg-amber-100 px-2.5 py-2 text-xs text-amber-900">
                      该候选稿疑似由 Mock 模式生成，标题/摘要包含提示词回显。建议关闭 `WRITER_LLM_USE_MOCK` 后重新生成。
                    </p>
                  ) : (
                    <p className="mt-2 text-sm text-graphite/85">{candidate.summary || "无摘要"}</p>
                  )}
                  <details className="mt-2 rounded-lg border border-ink/10 bg-white/80 p-2">
                    <summary className="cursor-pointer text-xs font-medium text-ocean">查看候选稿全文</summary>
                    <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">
                      {sanitizeContentField(candidate.content) || "无正文内容"}
                    </pre>
                  </details>
                  <p className="mt-2 text-xs text-graphite/65">生成时间：{formatDate(candidate.created_at)}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button type="button" size="sm" onClick={() => withErrorBoundary(() => approveCandidate(candidate.id))()}>
                      <CheckCircle2 className="mr-1.5 h-4 w-4" />通过并继续
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      onClick={() => withErrorBoundary(() => rejectCandidate(candidate.id))()}
                    >
                      <XCircle className="mr-1.5 h-4 w-4" />拒绝（保持待审）
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </Card>
      </div>

      {selectedProjectId && <StoryAssetsPanel projectId={selectedProjectId} />}

      <Card className="p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink">故事时间线</h2>
          <span className="text-sm text-graphite/70">现代化可视化进程</span>
        </div>

        {!selectedProjectId ? (
          <EmptyState title="请先选择项目" description="选择项目后显示该项目故事时间线。" />
        ) : timelineItems.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-ink/20 bg-white/60 p-6 text-sm text-graphite/75">
            <p className="font-medium text-ink">没有设置故事线</p>
            <p className="mt-1">可在“项目初始化”弹窗里填写 timeline_lines，或后续在故事资产中维护时间线事件。</p>
          </div>
        ) : (
          <div className="relative ml-2 max-h-[420px] space-y-4 overflow-auto pr-2">
            <div className="absolute bottom-0 left-3 top-1 w-px bg-gradient-to-b from-ocean/55 via-surge/40 to-ember/35" />
            {timelineItems.map((item) => (
              <div key={item.id} className="relative pl-10">
                <div className="absolute left-[6px] top-5 h-3.5 w-3.5 rounded-full border-2 border-white bg-gradient-to-br from-ocean to-surge shadow" />
                <article className="rounded-xl border border-ink/10 bg-white/80 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-semibold text-ink">{item.event_title || "未命名事件"}</h3>
                    <span className="inline-flex items-center gap-1 rounded-full bg-ocean/10 px-2 py-1 text-xs text-ocean">
                      <Clock3 className="h-3.5 w-3.5" />
                      {item.chapter_no ? `第 ${item.chapter_no} 章` : "未绑定章节"}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-graphite/80">{item.event_desc || "暂无描述"}</p>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs text-graphite/65">
                    {item.location ? <span>地点：{item.location}</span> : null}
                    {item.involved_characters?.length ? <span>角色：{item.involved_characters.join("、")}</span> : null}
                    <span>{formatDate(item.created_at)}</span>
                  </div>
                </article>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card className="p-5">
        <h3 className="font-[var(--font-display)] text-xl font-semibold text-ink">日志与排障</h3>
        <p className="mt-2 text-sm text-graphite/75">
          运行细节可在
          {lastTimelineRunId || activeRunId ? (
            <Link
              className="ml-1 text-ocean underline underline-offset-2"
              href={`/runs/${lastTimelineRunId || activeRunId}`}
            >
              Run Timeline
            </Link>
          ) : (
            <span className="ml-1 font-medium text-graphite/80">Run Timeline（创建 run 后可点）</span>
          )}
          查看。API 会将编排与 LLM 诊断分别写入 `data/worker.log`、`data/llm.log`；其余仍见进程 stdout。
        </p>
      </Card>

      {globalError ? <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{globalError}</p> : null}
      {globalMessage ? (
        <p className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">{globalMessage}</p>
      ) : null}

      <Modal
        open={newProjectOpen}
        title="新建项目"
        onClose={() => setNewProjectOpen(false)}
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setNewProjectOpen(false)}>
              取消
            </Button>
            <Button type="button" onClick={() => withErrorBoundary(createProject)()} disabled={createProjectForm.formState.isSubmitting}>
              {createProjectForm.formState.isSubmitting ? "创建中..." : "创建项目"}
            </Button>
          </div>
        }
      >
        <form className="space-y-4" onSubmit={withErrorBoundary(createProject)}>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">项目名</span>
            <input
              {...createProjectForm.register("title")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              placeholder="例如：雾港纪事"
            />
            <p className="mt-1 text-xs text-rose-700">{createProjectForm.formState.errors.title?.message}</p>
          </label>

          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">题材</span>
            <input
              {...createProjectForm.register("genre")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              placeholder="悬疑 / 科幻 / 奇幻"
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">故事前提</span>
            <textarea
              {...createProjectForm.register("premise")}
              className="min-h-24 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              placeholder="一句话描述主线冲突"
            />
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">可见性</span>
              <select
                {...createProjectForm.register("visibility")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              >
                <option value="members">成员可见（默认）</option>
                <option value="private">仅自己可见</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">目标读者</span>
              <input
                {...createProjectForm.register("target_audience")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
                placeholder="例如：青年读者"
              />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">叙事语气</span>
              <input
                {...createProjectForm.register("tone")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
                placeholder="例如：克制、冷峻"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">标签（逗号分隔）</span>
              <input
                {...createProjectForm.register("tags_text")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
                placeholder="成长, 冒险, 反转"
              />
            </label>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(editingProject)}
        title="项目设置"
        onClose={() => setEditProjectId(null)}
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setEditProjectId(null)}>
              取消
            </Button>
            <Button type="button" onClick={() => withErrorBoundary(updateProject)()} disabled={editProjectForm.formState.isSubmitting}>
              {editProjectForm.formState.isSubmitting ? "保存中..." : "保存设置"}
            </Button>
          </div>
        }
      >
        <form className="space-y-4" onSubmit={withErrorBoundary(updateProject)}>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">项目名</span>
            <input
              {...editProjectForm.register("title")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            />
            <p className="mt-1 text-xs text-rose-700">{editProjectForm.formState.errors.title?.message}</p>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">题材</span>
            <input
              {...editProjectForm.register("genre")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">故事前提</span>
            <textarea
              {...editProjectForm.register("premise")}
              className="min-h-20 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            />
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">可见性</span>
              <select
                {...editProjectForm.register("visibility")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              >
                <option value="members">成员可见（默认）</option>
                <option value="private">仅自己可见</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">目标读者</span>
              <input
                {...editProjectForm.register("target_audience")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              />
            </label>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">叙事语气</span>
              <input
                {...editProjectForm.register("tone")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-sm font-medium text-graphite">标签（逗号分隔）</span>
              <input
                {...editProjectForm.register("tags_text")}
                className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
              />
            </label>
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(bootstrapTargetProject)}
        title={`初始化项目：${bootstrapTargetProject?.title || ""}`}
        onClose={() => setBootstrapProjectId(null)}
        widthClassName="max-w-3xl"
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setBootstrapProjectId(null)}>
              取消
            </Button>
            <Button type="button" onClick={() => withErrorBoundary(submitBootstrapProject)()} disabled={bootstrapForm.formState.isSubmitting}>
              {bootstrapForm.formState.isSubmitting ? "初始化中..." : "执行初始化"}
            </Button>
          </div>
        }
      >
        <form className="space-y-4" onSubmit={withErrorBoundary(submitBootstrapProject)}>
          {bootstrapTargetProject?.premise && (
            <div className="rounded-xl border border-sky-200 bg-sky-50 p-3">
              <p className="text-xs text-sky-700">
                故事前提：<span className="font-medium">{bootstrapTargetProject.premise}</span>
              </p>
            </div>
          )}

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-graphite">大纲</span>
              <Button size="sm" type="button" variant="secondary" disabled={!!aiGenerating.outline} onClick={() => aiGenerateAsset("outline")}>
                {aiGenerating.outline ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />生成中...</> : <><Sparkles className="mr-1 h-3.5 w-3.5" />AI 生成大纲</>}
              </Button>
            </div>
            <input {...bootstrapForm.register("outline_title")} className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2" placeholder="大纲标题（如：第一卷·迷雾之门）" />
            <textarea {...bootstrapForm.register("outline_content")} className="min-h-24 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2" placeholder="概述主要矛盾与阶段目标" />
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-graphite">角色（每行一个）</span>
              <Button size="sm" type="button" variant="secondary" disabled={!!aiGenerating.characters} onClick={() => aiGenerateAsset("characters")}>
                {aiGenerating.characters ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />生成中...</> : <><Sparkles className="mr-1 h-3.5 w-3.5" />AI 生成角色</>}
              </Button>
            </div>
            <textarea {...bootstrapForm.register("character_lines")} className="min-h-20 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 font-mono text-xs outline-none ring-surge/50 focus:ring-2" placeholder={'格式：姓名|角色类型|阵营|年龄\n例如：林雾|protagonist|自由人|19'} />
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-graphite">世界观条目（每行一个）</span>
              <Button size="sm" type="button" variant="secondary" disabled={!!aiGenerating.world_entries} onClick={() => aiGenerateAsset("world_entries")}>
                {aiGenerating.world_entries ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />生成中...</> : <><Sparkles className="mr-1 h-3.5 w-3.5" />AI 生成世界观</>}
              </Button>
            </div>
            <textarea {...bootstrapForm.register("world_lines")} className="min-h-20 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 font-mono text-xs outline-none ring-surge/50 focus:ring-2" placeholder={'格式：标题|类型|内容\n例如：奇迹道具协会|faction|管理危险道具流通'} />
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-graphite">时间线事件（每行一个）</span>
              <Button size="sm" type="button" variant="secondary" disabled={!!aiGenerating.timeline} onClick={() => aiGenerateAsset("timeline")}>
                {aiGenerating.timeline ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />生成中...</> : <><Sparkles className="mr-1 h-3.5 w-3.5" />AI 生成时间线</>}
              </Button>
            </div>
            <textarea {...bootstrapForm.register("timeline_lines")} className="min-h-20 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 font-mono text-xs outline-none ring-surge/50 focus:ring-2" placeholder={'格式：章节号|标题|描述|地点|角色1,角色2\n例如：1|觉醒|主角首次激活道具|旧码头|林雾,江沉'} />
          </div>

          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-graphite">伏笔（每行一个）</span>
              <Button size="sm" type="button" variant="secondary" disabled={!!aiGenerating.foreshadowing} onClick={() => aiGenerateAsset("foreshadowing")}>
                {aiGenerating.foreshadowing ? <><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />生成中...</> : <><Sparkles className="mr-1 h-3.5 w-3.5" />AI 生成伏笔</>}
              </Button>
            </div>
            <textarea {...bootstrapForm.register("foreshadowing_lines")} className="min-h-20 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 font-mono text-xs outline-none ring-surge/50 focus:ring-2" placeholder={'格式：埋设章节|埋设内容|预期回收|回收章节|回收内容|状态(open/resolved)'} />
          </div>
        </form>
      </Modal>

      <Modal
        open={Boolean(selectedChapter)}
        title={selectedChapter ? `编辑章节：第 ${selectedChapter.chapter_no} 章` : "编辑章节"}
        onClose={() => setChapterEditId(null)}
        widthClassName="max-w-3xl"
        footer={
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setChapterEditId(null)}>
              取消
            </Button>
            <Button type="button" onClick={() => withErrorBoundary(saveChapter)()} disabled={chapterEditForm.formState.isSubmitting}>
              {chapterEditForm.formState.isSubmitting ? "保存中..." : "保存并生成新版本"}
            </Button>
          </div>
        }
      >
        <form className="space-y-4" onSubmit={withErrorBoundary(saveChapter)}>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">章节标题</span>
            <input
              {...chapterEditForm.register("title")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">摘要</span>
            <textarea
              {...chapterEditForm.register("summary")}
              className="min-h-20 w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">正文</span>
            <textarea
              {...chapterEditForm.register("content")}
              className="min-h-[260px] w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-graphite">状态</span>
            <select
              {...chapterEditForm.register("status")}
              className="w-full rounded-xl border border-ink/20 bg-white px-3 py-2 outline-none ring-surge/50 focus:ring-2"
            >
              <option value="draft">草稿</option>
              <option value="published">已发布</option>
            </select>
          </label>

          {selectedChapter && chapterModalProtagonist ? (
            <div className="rounded-xl border border-ocean/25 bg-ocean/[0.06] p-4 text-sm text-graphite/85">
              <p className="font-semibold text-ink">
                本章视角 · {chapterModalProtagonist.name}
                {String(chapterModalProtagonist.role_type || "").toLowerCase() === "protagonist" ? "（主角）" : ""}
              </p>
              <p className="mt-1 text-xs text-graphite/60">
                与写作链路一致：存在章节快照时优先生效。完整编辑请在本页下方「故事资产」→ 角色卡片中打开详情。
              </p>
              {chapterModalAssetSnap ? (
                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  <div>
                    <p className="text-xs font-medium text-graphite/70">物品 inventory</p>
                    <pre className="mt-1 max-h-28 overflow-auto rounded-lg bg-white/80 p-2 text-[11px] leading-snug text-slate-700">
                      {JSON.stringify(chapterModalAssetSnap.inventory_json || {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-graphite/70">财富 wealth</p>
                    <pre className="mt-1 max-h-28 overflow-auto rounded-lg bg-white/80 p-2 text-[11px] leading-snug text-slate-700">
                      {JSON.stringify(chapterModalAssetSnap.wealth_json || {}, null, 2)}
                    </pre>
                  </div>
                </div>
              ) : (
                <p className="mt-2 text-xs text-graphite/55">正在加载快照…</p>
              )}
            </div>
          ) : selectedChapter ? (
            <p className="text-xs text-graphite/55">当前项目暂无角色，无法展示本章携带物参考。</p>
          ) : null}
        </form>
      </Modal>

      <Modal
        open={Boolean(versionChapterId)}
        title="章节版本历史"
        onClose={() => {
          setVersionChapterId(null);
          setPreviewVersionId(null);
        }}
        widthClassName="max-w-4xl"
      >
        {versionsLoading ? (
          <p className="text-sm text-graphite/70">版本加载中...</p>
        ) : (versionsData?.items || []).length === 0 ? (
          <EmptyState title="没有版本记录" description="当前章节尚无版本。" />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
            <div className="max-h-[52vh] space-y-2 overflow-auto pr-1">
              {(versionsData?.items || []).map((version) => (
                <article key={version.id} className="rounded-xl border border-ink/10 bg-white p-3">
                  <p className="text-sm font-semibold text-ink">v{version.version_no}</p>
                  <p className="mt-1 text-xs text-graphite/65">
                    {formatDate(version.created_at)} · {version.source_agent || "unknown"}/{version.source_workflow || "unknown"}
                  </p>
                  <div className="mt-2 flex gap-2">
                    <Button size="sm" variant="secondary" type="button" onClick={() => setPreviewVersionId(version.id)}>
                      <FileStack className="mr-1.5 h-4 w-4" />预览
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      type="button"
                      onClick={() => withErrorBoundary(() => rollbackChapter(version.chapter_id, version.version_no))()}
                    >
                      回滚到此版本
                    </Button>
                  </div>
                </article>
              ))}
            </div>
            <div className="rounded-xl border border-ink/10 bg-white p-4">
              {previewVersion ? (
                <>
                  <p className="text-sm font-semibold text-ink">预览版本 v{previewVersion.version_no}</p>
                  <p className="mt-1 text-xs text-graphite/65">{formatDate(previewVersion.created_at)}</p>
                  <p className="mt-3 text-sm text-graphite/85">{previewVersion.summary || "无摘要"}</p>
                  <pre className="mt-3 max-h-[36vh] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
                    {previewVersion.content || "无内容"}
                  </pre>
                </>
              ) : (
                <p className="text-sm text-graphite/70">左侧选择一个版本进行预览。</p>
              )}
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
