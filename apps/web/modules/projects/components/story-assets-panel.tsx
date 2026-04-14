"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Globe, PenLine, PlusCircle, Trash2, User2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/shared/ui/button";
import { Card } from "@/shared/ui/card";
import { Modal } from "@/shared/ui/modal";
import { toast } from "@/shared/ui/toast";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { credentials: "include", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(String((body as { detail?: string }).detail || "请求失败"));
  return body as T;
}

/** 从 profile_json 中提取可读摘要，与 BFF 返回字段对齐。 */
function characterProfileSnippet(profile: Record<string, unknown> | null | undefined): string | null {
  if (!profile || typeof profile !== "object") return null;
  if (Object.keys(profile).length === 0) return null;
  const keys = ["bio", "summary", "background", "description", "appearance", "motivation", "personality"];
  for (const k of keys) {
    const v = profile[k];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  try {
    const s = JSON.stringify(profile);
    return s.length > 220 ? `${s.slice(0, 220)}…` : s;
  } catch {
    return null;
  }
}

interface Character {
  id: string;
  name: string;
  role_type: string | null;
  age: number | null;
  faction: string | null;
  profile_json: Record<string, unknown>;
  inventory_json: Record<string, unknown>;
  wealth_json: Record<string, unknown>;
}

interface WorldEntry {
  id: string;
  entry_type: string | null;
  title: string;
  content: string | null;
}

interface Outline {
  id: string;
  version_no: number;
  title: string | null;
  content: string | null;
  structure_json: Record<string, unknown> | null;
  is_active: boolean;
}

interface TimelineEvent {
  id: string;
  chapter_no: number | null;
  event_title: string | null;
  event_desc: string | null;
  location: string | null;
  involved_characters: string[];
}

type AssetTab = "outline" | "characters" | "world" | "timeline";

/** 下拉展示上限：避免上千章时一次渲染过多 option 阻塞主线程 */
const CHAPTER_SELECT_MAX_OPTIONS = 800;

interface ChapterListItem {
  id: string;
  chapter_no: number;
  title: string | null;
}

export function StoryAssetsPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<AssetTab>("outline");
  const [addingCharacter, setAddingCharacter] = useState(false);
  const [addingWorld, setAddingWorld] = useState(false);
  const [detailCharacterId, setDetailCharacterId] = useState<string | null>(null);
  const [invEdit, setInvEdit] = useState("{}");
  const [wealthEdit, setWealthEdit] = useState("{}");
  const [snapChapterNo, setSnapChapterNo] = useState("1");
  const [snapInv, setSnapInv] = useState("{}");
  const [snapWealth, setSnapWealth] = useState("{}");
  const [snapLoading, setSnapLoading] = useState(false);

  const { data: outline } = useQuery<Outline>({
    queryKey: ["outline", projectId],
    queryFn: () => fetchJson(`/api/projects/${projectId}/outlines`),
    retry: false,
  });

  const { data: characters, refetch: refetchCharacters } = useQuery<{ items: Character[] }>({
    queryKey: ["characters", projectId],
    queryFn: () => fetchJson(`/api/projects/${projectId}/characters`),
  });

  const { data: worldEntries, refetch: refetchWorld } = useQuery<{ items: WorldEntry[] }>({
    queryKey: ["world-entries", projectId],
    queryFn: () => fetchJson(`/api/projects/${projectId}/world-entries`),
  });

  const { data: timelineEvents, refetch: refetchTimeline } = useQuery<{ items: TimelineEvent[] }>({
    queryKey: ["timeline-events-asset", projectId],
    queryFn: () => fetchJson(`/api/projects/${projectId}/timeline-events?limit=200`),
  });

  /** 仅在打开角色详情弹窗时拉取章节列表；不含正文，体量小；长缓存减少重复请求 */
  const { data: chaptersLight, isFetching: chaptersLightLoading } = useQuery<{ items: ChapterListItem[] }>({
    queryKey: ["chapters", projectId, "story-assets-character-modal"],
    queryFn: () => fetchJson(`/api/projects/${projectId}/chapters?include_content=0`),
    enabled: Boolean(projectId && detailCharacterId),
    staleTime: 120_000,
    gcTime: 600_000,
    refetchOnWindowFocus: false,
  });

  const chapterDropdown = useMemo(() => {
    const raw = chaptersLight?.items || [];
    const sorted = [...raw].sort((a, b) => a.chapter_no - b.chapter_no);
    const total = sorted.length;
    const rows = sorted.slice(0, CHAPTER_SELECT_MAX_OPTIONS);
    return { rows, total, truncated: total > CHAPTER_SELECT_MAX_OPTIONS };
  }, [chaptersLight]);

  const detailCharacter = useMemo(
    () => (characters?.items || []).find((c) => c.id === detailCharacterId) || null,
    [characters?.items, detailCharacterId],
  );

  useEffect(() => {
    if (!detailCharacter) return;
    setInvEdit(JSON.stringify(detailCharacter.inventory_json || {}, null, 2));
    setWealthEdit(JSON.stringify(detailCharacter.wealth_json || {}, null, 2));
  }, [detailCharacter]);

  /** 章节列表到达后，若当前选中章不在列表中则切到第一章（避免无效章节号） */
  useEffect(() => {
    if (!detailCharacterId) return;
    const raw = chaptersLight?.items || [];
    const rows = [...raw].sort((a, b) => a.chapter_no - b.chapter_no).slice(0, CHAPTER_SELECT_MAX_OPTIONS);
    if (!rows.length) return;
    setSnapChapterNo((prev) => (rows.some((c) => String(c.chapter_no) === prev) ? prev : String(rows[0].chapter_no)));
  }, [detailCharacterId, chaptersLight]);

  const saveCharacterAssets = async () => {
    if (!detailCharacter) return;
    let inv: Record<string, unknown>;
    let wealth: Record<string, unknown>;
    try {
      inv = JSON.parse(invEdit) as Record<string, unknown>;
      wealth = JSON.parse(wealthEdit) as Record<string, unknown>;
    } catch {
      toast.error("物品或财富的 JSON 格式不正确");
      return;
    }
    await fetchJson(`/api/projects/${projectId}/characters/${detailCharacter.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ inventory_json: inv, wealth_json: wealth }),
    });
    await refetchCharacters();
    toast.success("角色物品与财富已保存");
  };

  const loadChapterSnapshot = async () => {
    if (!detailCharacter) return;
    const n = Number(snapChapterNo);
    if (!Number.isFinite(n) || n < 1) {
      toast.error("请输入有效章节号");
      return;
    }
    setSnapLoading(true);
    try {
      const data = await fetchJson<{
        inventory_json: Record<string, unknown>;
        wealth_json: Record<string, unknown>;
        has_snapshot: boolean;
      }>(
        `/api/projects/${projectId}/characters/${detailCharacter.id}/chapter-assets?chapter_no=${n}`,
      );
      setSnapInv(JSON.stringify(data.inventory_json || {}, null, 2));
      setSnapWealth(JSON.stringify(data.wealth_json || {}, null, 2));
      toast.info(data.has_snapshot ? "已加载本章快照" : "本章尚无快照，可编辑后保存");
    } catch (e) {
      toast.error(String((e as Error).message));
    } finally {
      setSnapLoading(false);
    }
  };

  const saveChapterSnapshot = async () => {
    if (!detailCharacter) return;
    const n = Number(snapChapterNo);
    if (!Number.isFinite(n) || n < 1) {
      toast.error("请输入有效章节号");
      return;
    }
    let inv: Record<string, unknown>;
    let wealth: Record<string, unknown>;
    try {
      inv = JSON.parse(snapInv) as Record<string, unknown>;
      wealth = JSON.parse(snapWealth) as Record<string, unknown>;
    } catch {
      toast.error("快照 JSON 格式不正确");
      return;
    }
    await fetchJson(`/api/projects/${projectId}/characters/${detailCharacter.id}/chapter-assets`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chapter_no: n, inventory_json: inv, wealth_json: wealth }),
    });
    toast.success("章节快照已保存");
  };

  const tabs: { key: AssetTab; label: string; icon: typeof BookOpen; count: number }[] = [
    { key: "outline", label: "大纲", icon: BookOpen, count: outline ? 1 : 0 },
    { key: "characters", label: "角色", icon: User2, count: characters?.items?.length || 0 },
    { key: "world", label: "世界观", icon: Globe, count: worldEntries?.items?.length || 0 },
    { key: "timeline", label: "时间线", icon: PenLine, count: timelineEvents?.items?.length || 0 },
  ];

  const addCharacter = async (form: HTMLFormElement) => {
    const fd = new FormData(form);
    const descRaw = fd.get("description");
    const desc = typeof descRaw === "string" && descRaw.trim() ? descRaw.trim() : "";
    await fetchJson(`/api/projects/${projectId}/characters`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: fd.get("name"),
        role_type: fd.get("role_type") || "supporting",
        profile_json: desc ? { bio: desc } : {},
      }),
    });
    await refetchCharacters();
    setAddingCharacter(false);
    toast.success("角色已添加");
  };

  const deleteCharacter = async (id: string) => {
    await fetchJson(`/api/projects/${projectId}/characters/${id}`, { method: "DELETE" });
    await refetchCharacters();
    toast.success("角色已删除");
  };

  const addWorldEntry = async (form: HTMLFormElement) => {
    const fd = new FormData(form);
    await fetchJson(`/api/projects/${projectId}/world-entries`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        entry_type: fd.get("entry_type") || "rule",
        title: fd.get("title"),
        content: fd.get("content") || null,
      }),
    });
    await refetchWorld();
    setAddingWorld(false);
    toast.success("世界观条目已添加");
  };

  const deleteWorldEntry = async (id: string) => {
    await fetchJson(`/api/projects/${projectId}/world-entries/${id}`, { method: "DELETE" });
    await refetchWorld();
    toast.success("条目已删除");
  };

  const addTimelineEvent = async (form: HTMLFormElement) => {
    const fd = new FormData(form);
    const chapterRaw = fd.get("chapter_no");
    const chapterNo =
      typeof chapterRaw === "string" && chapterRaw.trim() !== "" ? Number(chapterRaw) : null;
    await fetchJson(`/api/projects/${projectId}/timeline-events`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        event_title: fd.get("title") || null,
        event_desc: fd.get("description") || null,
        chapter_no: chapterNo != null && Number.isFinite(chapterNo) ? chapterNo : null,
        location: fd.get("location") || null,
      }),
    });
    await refetchTimeline();
    toast.success("时间线事件已添加");
  };

  const deleteTimelineEvent = async (id: string) => {
    await fetchJson(`/api/projects/${projectId}/timeline-events/${id}`, { method: "DELETE" });
    await refetchTimeline();
    toast.success("事件已删除");
  };

  return (
    <Card className="p-6">
      <h2 className="font-[var(--font-display)] text-2xl font-semibold text-ink mb-4">故事资产</h2>

      {/* Tab 栏 */}
      <div className="flex gap-1 rounded-xl bg-slate-100 p-1 mb-4">
        {tabs.map((t) => {
          const Icon = t.icon;
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              type="button"
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                active ? "bg-white text-ink shadow-sm" : "text-graphite/70 hover:text-ink"
              }`}
              onClick={() => setTab(t.key)}
            >
              <Icon className="h-4 w-4" />
              {t.label}
              <span className="ml-1 text-xs text-graphite/50">{t.count}</span>
            </button>
          );
        })}
      </div>

      {/* 大纲 */}
      {tab === "outline" && (
        <div>
          {outline ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-ink">{outline.title || "当前大纲"}</h3>
                <span className="text-xs text-graphite/55">v{outline.version_no} {outline.is_active ? "· 激活" : ""}</span>
              </div>
              {outline.content && (
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                  {outline.content}
                </pre>
              )}
              {outline.structure_json && Object.keys(outline.structure_json).length > 0 && (
                <details className="rounded-lg border border-ink/10 p-2">
                  <summary className="cursor-pointer text-xs font-medium text-ocean">结构化数据</summary>
                  <pre className="mt-2 max-h-40 overflow-auto text-xs text-slate-600">
                    {JSON.stringify(outline.structure_json, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          ) : (
            <p className="text-sm text-graphite/70">当前项目暂无大纲。可通过「初始化」按钮或运行 writing_full 工作流自动生成。</p>
          )}
        </div>
      )}

      {/* 角色 */}
      {tab === "characters" && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <Button size="sm" type="button" onClick={() => setAddingCharacter(true)}>
              <PlusCircle className="mr-1.5 h-4 w-4" />添加角色
            </Button>
          </div>
          {addingCharacter && (
            <form
              className="rounded-xl border border-ocean/30 bg-ocean/5 p-3 space-y-2"
              onSubmit={(e) => { e.preventDefault(); addCharacter(e.currentTarget); }}
            >
              <input name="name" required placeholder="角色名" className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
              <select name="role_type" className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm">
                <option value="protagonist">主角</option>
                <option value="antagonist">反派</option>
                <option value="supporting">配角</option>
                <option value="minor">路人</option>
              </select>
              <textarea name="description" placeholder="角色描述" rows={2} className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
              <div className="flex gap-2 justify-end">
                <Button size="sm" variant="secondary" type="button" onClick={() => setAddingCharacter(false)}>取消</Button>
                <Button size="sm" type="submit">保存</Button>
              </div>
            </form>
          )}
          {(characters?.items || []).length === 0 && !addingCharacter && (
            <p className="text-sm text-graphite/70">暂无角色数据。</p>
          )}
          {(characters?.items || []).map((c) => {
            const snippet = characterProfileSnippet(c.profile_json);
            return (
            <div
              key={c.id}
              className="flex items-start justify-between gap-2 rounded-xl border border-ink/10 bg-white p-3"
            >
              <button
                type="button"
                className="min-w-0 flex-1 text-left rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ocean/40"
                onClick={() => setDetailCharacterId(c.id)}
              >
                <p className="font-semibold text-ink">{c.name}</p>
                <p className="text-xs text-graphite/55">
                  {[c.role_type || "supporting", c.faction, c.age != null ? `${c.age} 岁` : null].filter(Boolean).join(" · ")}
                </p>
                {snippet ? (
                  <p className="mt-1 text-sm text-graphite/80 line-clamp-2">{snippet}</p>
                ) : (
                  <p className="mt-1 text-xs text-graphite/45">点击编辑设定、物品与财富…</p>
                )}
              </button>
              <button
                type="button"
                className="shrink-0 rounded p-1 text-graphite/40 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                onClick={() => { if (window.confirm(`删除角色「${c.name}」？`)) deleteCharacter(c.id); }}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
            );
          })}
        </div>
      )}

      {/* 世界观 */}
      {tab === "world" && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <Button size="sm" type="button" onClick={() => setAddingWorld(true)}>
              <PlusCircle className="mr-1.5 h-4 w-4" />添加条目
            </Button>
          </div>
          {addingWorld && (
            <form
              className="rounded-xl border border-ocean/30 bg-ocean/5 p-3 space-y-2"
              onSubmit={(e) => { e.preventDefault(); addWorldEntry(e.currentTarget); }}
            >
              <input name="title" required placeholder="条目标题" className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
              <select name="entry_type" className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm">
                <option value="rule">规则</option>
                <option value="location">地点</option>
                <option value="faction">势力</option>
                <option value="concept">概念</option>
                <option value="item">道具</option>
              </select>
              <textarea name="content" placeholder="描述内容" rows={2} className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
              <div className="flex gap-2 justify-end">
                <Button size="sm" variant="secondary" type="button" onClick={() => setAddingWorld(false)}>取消</Button>
                <Button size="sm" type="submit">保存</Button>
              </div>
            </form>
          )}
          {(worldEntries?.items || []).length === 0 && !addingWorld && (
            <p className="text-sm text-graphite/70">暂无世界观数据。</p>
          )}
          {(worldEntries?.items || []).map((w) => (
            <div key={w.id} className="flex items-start justify-between rounded-xl border border-ink/10 bg-white p-3">
              <div>
                <p className="font-semibold text-ink">{w.title}</p>
                <p className="text-xs text-graphite/55">{w.entry_type || "rule"}</p>
                {w.content && <p className="mt-1 text-sm text-graphite/80 line-clamp-2">{w.content}</p>}
              </div>
              <button
                type="button"
                className="shrink-0 rounded p-1 text-graphite/40 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                onClick={() => { if (window.confirm(`删除「${w.title}」？`)) deleteWorldEntry(w.id); }}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* 时间线 */}
      {tab === "timeline" && (
        <div className="space-y-3">
          <details>
            <summary className="cursor-pointer text-sm font-medium text-ocean">添加时间线事件</summary>
            <form
              className="mt-2 rounded-xl border border-ocean/30 bg-ocean/5 p-3 space-y-2"
              onSubmit={(e) => { e.preventDefault(); addTimelineEvent(e.currentTarget); (e.currentTarget as HTMLFormElement).reset(); }}
            >
              <input name="title" required placeholder="事件标题" className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
              <div className="grid grid-cols-2 gap-2">
                <input name="location" placeholder="地点（可选）" className="rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
                <input name="chapter_no" type="number" min="1" placeholder="章节号（可选）" className="rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
              </div>
              <textarea name="description" placeholder="事件描述" rows={2} className="w-full rounded-lg border border-ink/20 px-3 py-1.5 text-sm" />
              <div className="flex justify-end">
                <Button size="sm" type="submit">添加</Button>
              </div>
            </form>
          </details>
          {(timelineEvents?.items || []).length === 0 && (
            <p className="text-sm text-graphite/70">暂无时间线数据。</p>
          )}
          <div className="relative pl-4 border-l-2 border-ocean/20 space-y-3">
            {(timelineEvents?.items || []).map((ev) => (
              <div key={ev.id} className="relative">
                <div className="absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full bg-ocean" />
                <div className="flex items-start justify-between rounded-xl border border-ink/10 bg-white p-3">
                  <div>
                    <p className="font-semibold text-ink">{ev.event_title || "（无标题）"}</p>
                    {(ev.location || ev.chapter_no != null) && (
                      <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-xs text-graphite/55">
                        {ev.location ? <span>{ev.location}</span> : null}
                        {ev.chapter_no != null ? (
                          <span>
                            {ev.location ? "· " : ""}
                            第{ev.chapter_no}章
                          </span>
                        ) : null}
                      </div>
                    )}
                    {ev.event_desc && (
                      <p className="mt-1 text-sm text-graphite/80 line-clamp-2">{ev.event_desc}</p>
                    )}
                  </div>
                  <button
                    type="button"
                    className="shrink-0 rounded p-1 text-graphite/40 hover:text-rose-600 hover:bg-rose-50 transition-colors"
                    onClick={() => {
                      if (window.confirm(`删除事件「${ev.event_title || "未命名"}」？`)) deleteTimelineEvent(ev.id);
                    }}
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <Modal
        open={Boolean(detailCharacter)}
        title={detailCharacter ? `角色：${detailCharacter.name}` : "角色"}
        onClose={() => setDetailCharacterId(null)}
        widthClassName="max-w-3xl"
      >
        {detailCharacter ? (
          <div className="space-y-5 text-sm text-graphite/80">
            <p className="text-xs text-graphite/55">
              创作章节时，系统会将「默认物品/财富」与「本章快照」合并注入 LLM；快照优先。
            </p>
            <div>
              <p className="mb-1 font-medium text-ink">扩展设定（profile_json）</p>
              <p className="text-xs leading-relaxed">
                {characterProfileSnippet(detailCharacter.profile_json) || "（暂无 bio/summary 等字段，可在工作台通过 API 或后续表单扩展）"}
              </p>
            </div>
            <div>
              <label className="mb-1 block font-medium text-ink">默认物品 inventory_json</label>
              <textarea
                className="h-32 w-full rounded-lg border border-ink/15 bg-slate-50/80 p-2 font-mono text-xs"
                value={invEdit}
                onChange={(e) => setInvEdit(e.target.value)}
                spellCheck={false}
              />
            </div>
            <div>
              <label className="mb-1 block font-medium text-ink">默认财富 wealth_json</label>
              <textarea
                className="h-28 w-full rounded-lg border border-ink/15 bg-slate-50/80 p-2 font-mono text-xs"
                value={wealthEdit}
                onChange={(e) => setWealthEdit(e.target.value)}
                spellCheck={false}
              />
            </div>
            <Button type="button" size="sm" onClick={() => void saveCharacterAssets()}>
              保存默认物品/财富
            </Button>

            <div className="border-t border-ink/10 pt-4 space-y-2">
              <p className="font-medium text-ink">按章节快照</p>
              <div className="flex flex-wrap items-end gap-2">
                <div className="min-w-0 flex-1 basis-[220px]">
                  <label className="text-xs text-graphite/55" htmlFor="character-snap-chapter">
                    选择章节
                  </label>
                  <select
                    id="character-snap-chapter"
                    className="mt-0.5 block w-full max-w-md rounded-lg border border-ink/15 bg-white px-2 py-2 text-sm text-ink shadow-sm"
                    value={chapterDropdown.rows.length ? snapChapterNo : ""}
                    onChange={(e) => setSnapChapterNo(e.target.value)}
                    disabled={!chapterDropdown.rows.length || chaptersLightLoading}
                  >
                    {!chapterDropdown.rows.length ? (
                      <option value="">
                        {chaptersLightLoading ? "正在加载章节…" : "暂无章节（请在工作台创建章节）"}
                      </option>
                    ) : (
                      chapterDropdown.rows.map((ch) => (
                        <option key={ch.id} value={String(ch.chapter_no)}>
                          第{ch.chapter_no}章{ch.title ? ` · ${ch.title}` : ""}
                        </option>
                      ))
                    )}
                  </select>
                  {chapterDropdown.truncated ? (
                    <p className="mt-1 text-[11px] text-amber-800/90">
                      共 {chapterDropdown.total} 章，为性能仅列出前 {CHAPTER_SELECT_MAX_OPTIONS} 章（按章号升序）。
                    </p>
                  ) : null}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={snapLoading || !chapterDropdown.rows.length}
                  onClick={() => void loadChapterSnapshot()}
                >
                  {snapLoading ? "加载中…" : "加载快照"}
                </Button>
                <Button type="button" size="sm" disabled={!chapterDropdown.rows.length} onClick={() => void saveChapterSnapshot()}>
                  保存本章快照
                </Button>
              </div>
              <textarea
                className="h-24 w-full rounded-lg border border-ink/15 bg-slate-50/80 p-2 font-mono text-xs"
                value={snapInv}
                onChange={(e) => setSnapInv(e.target.value)}
                spellCheck={false}
                placeholder="本章 inventory 快照 JSON"
              />
              <textarea
                className="h-20 w-full rounded-lg border border-ink/15 bg-slate-50/80 p-2 font-mono text-xs"
                value={snapWealth}
                onChange={(e) => setSnapWealth(e.target.value)}
                spellCheck={false}
                placeholder="本章 wealth 快照 JSON"
              />
            </div>
          </div>
        ) : null}
      </Modal>
    </Card>
  );
}
