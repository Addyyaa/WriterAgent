"""一致性审查：规则引擎聚焦 + 证据包切片（不把全量 lore 直接塞进 LLM）。"""

from __future__ import annotations

import re
from typing import Any

from packages.workflows.chapter_generation.context_provider import StoryConstraintContext

# 证据包规模上限（随故事增长不线性放大 prompt）
_MAX_FOCUS_RULE_ISSUES = 12
_MAX_SLICED_CHARACTERS = 12
_MAX_SLICED_WORLD = 8
_MAX_SLICED_TIMELINE = 8
_MAX_SLICED_FORESHADOWING = 6
_MAX_PROFILE_KEYS = (
    "forbidden_behaviors",
    "must_not",
    "taboos",
    "abilities",
    "personality",
    "appearance",
)
_MAX_INVENTORY_ENTRIES = 8
_WORLD_CONTENT_CAP = 400
# 审查证据包内章节列表：邻章与当前章仅保留短 preview（全文仅在 chapter_draft_audit）
_CHAPTER_EVIDENCE_PREVIEW_CAP = 180
_MAX_FOCUS_ASSETS = 24
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}")


def build_review_contract() -> dict[str, Any]:
    """审查输出契约：与 review_focus 分离，供 Assembler 独立投影。"""
    return {
        "audit_dimensions": ["character", "worldview", "timeline", "foreshadowing"],
        "allowed_severities": ["warning", "failed"],
        "evidence_policy": (
            "仅可引用本请求 JSON 内 state.review_context、state.review_evidence_pack、"
            "state.review_focus、state.review_contract、state.chapter_draft_audit 与 retrieval 已给出片段；"
            "不得推断未出现的设定。"
        ),
    }


def _clip(text: str, limit: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[: max(1, limit - 3)] + "..."


def _is_foreshadowing_open(status: Any) -> bool:
    s = str(status or "").strip().lower()
    return s in {"open", "pending", "unresolved", "active"}


def characters_mentioned_in_text(characters: list[dict[str, Any]], text: str) -> list[str]:
    """按名称长度降序匹配；若长名已命中，则剔除为其真子串的短名（避免「李」「李四」双计）。"""
    names = [str(c.get("name") or "").strip() for c in characters if c.get("name")]
    names = sorted({n for n in names if n}, key=len, reverse=True)
    mentioned: list[str] = []
    for n in names:
        if n in text:
            mentioned.append(n)
    return [n for n in mentioned if not any(n != m and n in m for m in mentioned)]


def _is_protagonist_role(role_type: Any) -> bool:
    s = str(role_type or "")
    low = s.lower()
    if "protagonist" in low:
        return True
    return any(m in s for m in ("主角", "主人公"))


def _infer_primary_pov_character(
    characters: list[dict[str, Any]],
    focus_names: list[str],
    text: str,
) -> dict[str, Any] | None:
    """主视角启发式：主角 role_type 且出场；否则取 focus 中在正文首次出现最早者。"""
    for c in characters:
        name = str(c.get("name") or "").strip()
        if not name or name not in text:
            continue
        if _is_protagonist_role(c.get("role_type")):
            return {
                "id": c.get("id"),
                "name": name,
                "inference": "role_type_hint",
            }
    if not focus_names:
        return None
    positions: list[tuple[int, str]] = []
    for n in focus_names:
        pos = text.find(n)
        if pos >= 0:
            positions.append((pos, n))
    if not positions:
        return None
    positions.sort(key=lambda x: x[0])
    first_name = positions[0][1]
    for c in characters:
        if str(c.get("name") or "").strip() == first_name:
            return {
                "id": c.get("id"),
                "name": first_name,
                "inference": "first_focus_in_text",
            }
    return {"id": None, "name": first_name, "inference": "first_focus_in_text"}


def _build_focus_assets(
    characters: list[dict[str, Any]],
    names: set[str],
    text: str,
) -> list[dict[str, Any]]:
    """正文中命中键/值的库存与财富，结构化列出。"""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def push(
        *,
        cid: str,
        cname: str,
        kind: str,
        key: str,
        value_preview: str,
    ) -> None:
        tup = (cid, kind, key)
        if tup in seen:
            return
        seen.add(tup)
        out.append(
            {
                "character_id": cid,
                "character_name": cname,
                "kind": kind,
                "asset_key": key,
                "value_preview": value_preview,
            }
        )

    for c in characters:
        name = str(c.get("name") or "").strip()
        if name not in names:
            continue
        cid = str(c.get("id") or "")
        inv_eff = dict(c.get("effective_inventory_json") or {})
        inv_base = dict(c.get("inventory_json") or {})
        inv = inv_eff if inv_eff else inv_base
        for k, v in inv.items():
            vs = str(v).strip()
            if not vs:
                continue
            if str(k) in text or vs in text:
                push(
                    cid=cid,
                    cname=name,
                    kind="inventory",
                    key=str(k),
                    value_preview=_clip(vs, 100),
                )
            if len(out) >= _MAX_FOCUS_ASSETS:
                return out

        w_eff = dict(c.get("effective_wealth_json") or {})
        w_base = dict(c.get("wealth_json") or {})
        wealth = w_eff if w_eff else w_base
        for k, v in wealth.items():
            vs = str(v).strip()
            if not vs:
                continue
            if str(k) in text or vs in text:
                push(
                    cid=cid,
                    cname=name,
                    kind="wealth",
                    key=str(k),
                    value_preview=_clip(vs, 100),
                )
            if len(out) >= _MAX_FOCUS_ASSETS:
                return out

    return out


def _inventory_hints_for_characters(
    characters: list[dict[str, Any]],
    names: set[str],
    text: str,
) -> list[str]:
    """与 focus_assets 并存的只读摘要行（便于人读 log）。"""
    hints: list[str] = []
    for c in characters:
        name = str(c.get("name") or "").strip()
        if name not in names:
            continue
        inv = dict(c.get("effective_inventory_json") or c.get("inventory_json") or {})
        n_added = 0
        for k, v in inv.items():
            vs = str(v).strip()
            if not vs:
                continue
            if str(k) in text or vs in text:
                hints.append(f"{name}:{k}={_clip(vs, 80)}")
                n_added += 1
            if n_added >= _MAX_INVENTORY_ENTRIES:
                break
    return hints[:16]


def _world_keywords_from_text(
    world_entries: list[dict[str, Any]],
    text: str,
) -> list[str]:
    kws: list[str] = []
    for e in world_entries:
        title = str(e.get("title") or "").strip()
        if title and title in text:
            kws.append(title)
    return list(dict.fromkeys(kws))


def build_review_focus(
    *,
    chapter_text: str,
    chapter_no: int | None,
    story_context: StoryConstraintContext,
    rule_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """规则引擎之后的「审查焦点」：告诉 LLM 本次要核对哪些面（不含输出契约）。"""
    text = str(chapter_text or "")
    chars = list(story_context.characters or [])
    mentioned = characters_mentioned_in_text(chars, text)
    names_set = set(mentioned)
    world_kws = _world_keywords_from_text(list(story_context.world_entries or []), text)

    issue_blob = " ".join(
        str(i.get("evidence_context") or "") + " " + str(i.get("evidence_draft") or "")
        for i in rule_issues
    )
    timeline_ids: list[str] = []
    for ev in list(story_context.timeline_events or []):
        eid = str(ev.get("id") or "").strip()
        if not eid:
            continue
        etitle = str(ev.get("event_title") or "").strip()
        edesc = str(ev.get("event_desc") or "").strip()
        if etitle and (etitle in text or etitle in issue_blob):
            timeline_ids.append(eid)
        elif edesc and len(edesc) >= 4 and (edesc in text or edesc[:120] in issue_blob):
            timeline_ids.append(eid)
    timeline_ids = list(dict.fromkeys(timeline_ids))[:16]

    foreshadow_ids: list[str] = []
    for fs in list(story_context.foreshadowings or []):
        fid = str(fs.get("id") or "").strip()
        if not fid:
            continue
        st = str(fs.get("setup_text") or "")
        po = str(fs.get("payoff_text") or "")
        ex = str(fs.get("expected_payoff") or "")
        blob_fs = f"{st}\n{po}\n{ex}"
        if any(
            len(x) >= 4 and (x in text or x in issue_blob)
            for x in (st, po, ex)
            if x
        ):
            foreshadow_ids.append(fid)
        elif set(_TOKEN_RE.findall(text[:4000])) & set(_TOKEN_RE.findall(blob_fs[:1500])):
            foreshadow_ids.append(fid)
    foreshadow_ids = list(dict.fromkeys(foreshadow_ids))[:16]

    issue_compact: list[dict[str, Any]] = []
    for it in list(rule_issues)[:_MAX_FOCUS_RULE_ISSUES]:
        if not isinstance(it, dict):
            continue
        issue_compact.append(
            {
                "category": it.get("category"),
                "severity": it.get("severity"),
                "evidence_context": _clip(str(it.get("evidence_context") or ""), 280),
                "evidence_draft": _clip(str(it.get("evidence_draft") or ""), 280),
                "source": it.get("source"),
            }
        )

    pov = _infer_primary_pov_character(chars, mentioned, text)
    assets = _build_focus_assets(chars, names_set, text)

    return {
        "chapter_no": chapter_no,
        "focus_character_names": mentioned,
        "primary_pov_character": pov,
        "focus_assets": assets,
        "focus_world_keywords": world_kws,
        "focus_timeline_event_ids": timeline_ids,
        "focus_foreshadowing_ids": foreshadow_ids,
        "focus_inventory_hints": _inventory_hints_for_characters(chars, names_set, text),
        "rule_issues": issue_compact,
    }


def _slim_profile(profile: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _MAX_PROFILE_KEYS:
        if k not in profile:
            continue
        v = profile[k]
        if isinstance(v, str):
            out[k] = _clip(v, 220)
        elif isinstance(v, list):
            out[k] = [_clip(str(x), 120) for x in v[:12]]
        elif isinstance(v, dict):
            out[k] = {str(a): _clip(str(b), 100) for a, b in list(v.items())[:10]}
    return out


def _slim_character_for_audit(
    character: dict[str, Any],
    text: str,
) -> dict[str, Any]:
    inv = dict(character.get("effective_inventory_json") or character.get("inventory_json") or {})
    slim_inv: dict[str, Any] = {}
    for k, v in inv.items():
        vs = str(v).strip()
        if not vs:
            continue
        if str(k) in text or vs in text:
            slim_inv[str(k)] = v if len(vs) <= 160 else _clip(vs, 160)
        if len(slim_inv) >= _MAX_INVENTORY_ENTRIES:
            break
    profile = _slim_profile(dict(character.get("profile_json") or {}))
    return {
        "id": character.get("id"),
        "name": character.get("name"),
        "role_type": character.get("role_type"),
        "faction": character.get("faction"),
        "profile_json": profile,
        "effective_inventory_json": slim_inv,
        "effective_wealth_json": dict(character.get("effective_wealth_json") or {}) or None,
    }


def _score_world_entry(
    entry: dict[str, Any],
    text: str,
    keywords: list[str],
    *,
    rule_issues: list[dict[str, Any]],
    issue_blob: str,
) -> float:
    title = str(entry.get("title") or "").strip()
    content = str(entry.get("content") or "").strip()
    meta = dict(entry.get("metadata_json") or {})
    score = 0.0
    if title and title in text:
        score += 3.0
    if title in keywords:
        score += 2.0
    toks = set(_TOKEN_RE.findall(text[:8000]))
    ctoks = set(_TOKEN_RE.findall(content[:2000]))
    overlap = len(toks & ctoks)
    score += min(2.0, overlap * 0.08)
    ban = []
    for key in ("forbidden_terms", "forbidden_words", "ban_terms"):
        ban.extend([str(x) for x in list(meta.get(key) or []) if str(x).strip()])
    for term in ban:
        if term and term in text:
            score += 2.5

    has_worldview_issue = any(
        str((it or {}).get("category") or "").strip().lower() in {"worldview", "world"}
        for it in rule_issues
        if isinstance(it, dict)
    )
    if has_worldview_issue:
        score += 0.55
        ib = str(issue_blob or "")
        if title and title in ib:
            score += 1.15
        elif ctoks and ib:
            ib_toks = set(_TOKEN_RE.findall(ib[:3000]))
            if ib_toks & ctoks:
                score += min(0.9, len(ib_toks & ctoks) * 0.06)
    return score


def _build_chapter_evidence_rows(
    chapters: list[dict[str, Any]],
    chapter_no: int | None,
) -> list[dict[str, Any]]:
    """邻章与当前章均不得带全文 content，仅 summary + 短 preview。"""
    rows: list[dict[str, Any]] = []
    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        raw_no = ch.get("chapter_no")
        try:
            ch_int = int(raw_no) if raw_no is not None else None
        except (TypeError, ValueError):
            ch_int = None
        preview_src = str(ch.get("content_preview") or "").strip()
        row = {
            "id": ch.get("id"),
            "chapter_no": ch.get("chapter_no"),
            "title": ch.get("title"),
            "summary": ch.get("summary"),
            "content_preview": _clip(preview_src, _CHAPTER_EVIDENCE_PREVIEW_CAP),
        }
        if chapter_no is not None and ch_int is not None and ch_int == chapter_no:
            row["is_current_chapter"] = True
        rows.append(row)
    return rows


def build_review_context_slice(
    *,
    chapter_text: str,
    chapter_no: int | None,
    story_context: StoryConstraintContext,
    review_focus: dict[str, Any],
    rule_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """按焦点从候选池切片为「证据包」，供 LLM 做补充判断（非百科全书）。"""
    text = str(chapter_text or "")
    names = set(str(x) for x in (review_focus.get("focus_character_names") or []) if x)
    issue_blob = " ".join(
        str(i.get("evidence_context") or "") + str(i.get("evidence_draft") or "") for i in rule_issues
    )
    for c in list(story_context.characters or []):
        n = str(c.get("name") or "").strip()
        if n and n in issue_blob:
            names.add(n)

    sliced_chars: list[dict[str, Any]] = []
    for c in list(story_context.characters or []):
        n = str(c.get("name") or "").strip()
        if n in names:
            sliced_chars.append(_slim_character_for_audit(c, text))
    sliced_chars = sliced_chars[:_MAX_SLICED_CHARACTERS]

    chapters_out = _build_chapter_evidence_rows(
        list(story_context.chapters or []),
        chapter_no,
    )

    keywords = list(review_focus.get("focus_world_keywords") or [])
    world_scored: list[tuple[float, dict[str, Any]]] = []
    for e in list(story_context.world_entries or []):
        if not isinstance(e, dict):
            continue
        sc = _score_world_entry(
            e,
            text,
            keywords,
            rule_issues=rule_issues,
            issue_blob=issue_blob,
        )
        world_scored.append((sc, e))
    world_scored.sort(key=lambda x: -x[0])
    if world_scored and world_scored[0][0] <= 0.0:
        world_pick = world_scored[: min(3, len(world_scored))]
    else:
        world_pick = world_scored[:_MAX_SLICED_WORLD]
    world_out: list[dict[str, Any]] = []
    for _, e in world_pick:
        world_out.append(
            {
                "id": e.get("id"),
                "entry_type": e.get("entry_type"),
                "title": e.get("title"),
                "content": _clip(str(e.get("content") or ""), _WORLD_CONTENT_CAP),
                "metadata_json": e.get("metadata_json") or {},
            }
        )

    focus_tid = set(str(x) for x in (review_focus.get("focus_timeline_event_ids") or []) if x)

    timeline_out: list[dict[str, Any]] = []
    for ev in list(story_context.timeline_events or []):
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get("id") or "").strip()
        raw_no = ev.get("chapter_no")
        ev_ch: int | None = None
        if raw_no is not None:
            try:
                ev_ch = int(raw_no)
            except (TypeError, ValueError):
                ev_ch = None
        include = False
        if chapter_no is not None and ev_ch is not None:
            if ev_ch <= chapter_no:
                include = True
        elif chapter_no is None:
            include = True
        if eid and eid in focus_tid:
            include = True
        etitle = str(ev.get("event_title") or "").strip()
        edesc = str(ev.get("event_desc") or "").strip()
        if etitle and etitle in issue_blob:
            include = True
        if edesc and _clip(edesc, 80) in issue_blob:
            include = True
        if include:
            timeline_out.append(
                {
                    "id": eid or None,
                    "chapter_no": ev.get("chapter_no"),
                    "event_title": ev.get("event_title"),
                    "event_desc": _clip(str(ev.get("event_desc") or ""), 320),
                    "location": ev.get("location"),
                    "involved_characters": list(ev.get("involved_characters") or [])[:12],
                }
            )
    timeline_out = timeline_out[:_MAX_SLICED_TIMELINE]

    focus_fid = set(str(x) for x in (review_focus.get("focus_foreshadowing_ids") or []) if x)
    fore_out: list[dict[str, Any]] = []
    for item in list(story_context.foreshadowings or []):
        if not isinstance(item, dict):
            continue
        if not _is_foreshadowing_open(item.get("status")):
            continue
        fid = str(item.get("id") or "").strip()
        setup_ch = item.get("setup_chapter_no")
        try:
            setup_int = int(setup_ch) if setup_ch is not None else None
        except (TypeError, ValueError):
            setup_int = None
        if chapter_no is not None and setup_int is not None and setup_int > chapter_no:
            continue
        setup_text = str(item.get("setup_text") or "")
        payoff_text = str(item.get("payoff_text") or "")
        expected = str(item.get("expected_payoff") or "")
        hit_names = any(
            bool(n) and (n in setup_text or n in expected or n in payoff_text) for n in names
        )
        blob_fs = (setup_text + expected)[:2000]
        toks = set(_TOKEN_RE.findall(text[:6000]))
        stoks = set(_TOKEN_RE.findall(blob_fs))
        token_overlap = len(toks & stoks) >= 2
        in_focus = bool(fid and fid in focus_fid)
        past_setup = (
            chapter_no is not None
            and setup_int is not None
            and setup_int <= chapter_no
        )
        if hit_names or in_focus or (past_setup and token_overlap):
            fore_out.append(
                {
                    "id": fid or None,
                    "setup_chapter_no": item.get("setup_chapter_no"),
                    "setup_text": _clip(setup_text, 280),
                    "expected_payoff": _clip(expected, 200),
                    "payoff_chapter_no": item.get("payoff_chapter_no"),
                    "payoff_text": _clip(payoff_text, 200),
                    "status": item.get("status"),
                }
            )
        if len(fore_out) >= _MAX_SLICED_FORESHADOWING:
            break

    return {
        "chapters": chapters_out,
        "characters": sliced_chars,
        "world_entries": world_out,
        "timeline_events": timeline_out,
        "foreshadowings": fore_out,
    }


def build_review_evidence_pack(
    *,
    chapter_text: str,
    chapter_no: int | None,
    story_context: StoryConstraintContext,
    review_focus: dict[str, Any],
) -> dict[str, Any]:
    """
    服务端预取的「加深证据」（一档审查）：在 review_context 摘要之上补充可核对原文片段，
    避免模型自行决定查库范围；与 fetch_consistency_evidence 白名单配合使用。
    """
    text = str(chapter_text or "")
    names = {str(x).strip() for x in (review_focus.get("focus_character_names") or []) if x}
    focus_tid = {str(x).strip() for x in (review_focus.get("focus_timeline_event_ids") or []) if x}
    focus_fid = {str(x).strip() for x in (review_focus.get("focus_foreshadowing_ids") or []) if x}
    world_kws = [str(x).strip() for x in (review_focus.get("focus_world_keywords") or []) if x]

    characters_detail: list[dict[str, Any]] = []
    for c in list(story_context.characters or []):
        if not isinstance(c, dict):
            continue
        n = str(c.get("name") or "").strip()
        if n not in names:
            continue
        prof = dict(c.get("profile_json") or {})
        audit_prof: dict[str, Any] = {}
        for key in ("forbidden_behaviors", "must_not", "taboos", "abilities", "personality"):
            if key not in prof:
                continue
            v = prof[key]
            if isinstance(v, str):
                audit_prof[key] = _clip(v, 520)
            elif isinstance(v, list):
                audit_prof[key] = [_clip(str(x), 200) for x in v[:20]]
            elif isinstance(v, dict):
                audit_prof[key] = {str(a): _clip(str(b), 160) for a, b in list(v.items())[:16]}
        characters_detail.append(
            {
                "id": c.get("id"),
                "name": n,
                "role_type": c.get("role_type"),
                "faction": c.get("faction"),
                "profile_audit": audit_prof,
                "inventory_snapshot": dict(c.get("effective_inventory_json") or c.get("inventory_json") or {}),
                "wealth_snapshot": dict(c.get("effective_wealth_json") or c.get("wealth_json") or {}),
            }
        )
    characters_detail = characters_detail[:_MAX_SLICED_CHARACTERS]

    timeline_detail: list[dict[str, Any]] = []
    for ev in list(story_context.timeline_events or []):
        if not isinstance(ev, dict):
            continue
        eid = str(ev.get("id") or "").strip()
        if eid not in focus_tid:
            continue
        raw_no = ev.get("chapter_no")
        try:
            ev_ch = int(raw_no) if raw_no is not None else None
        except (TypeError, ValueError):
            ev_ch = None
        if chapter_no is not None and ev_ch is not None and ev_ch > chapter_no:
            continue
        timeline_detail.append(
            {
                "id": eid or ev.get("id"),
                "chapter_no": ev.get("chapter_no"),
                "event_title": ev.get("event_title"),
                "event_desc": _clip(str(ev.get("event_desc") or ""), 1200),
                "location": ev.get("location"),
                "involved_characters": list(ev.get("involved_characters") or [])[:16],
            }
        )

    foreshadowing_detail: list[dict[str, Any]] = []
    for item in list(story_context.foreshadowings or []):
        if not isinstance(item, dict):
            continue
        fid = str(item.get("id") or "").strip()
        if fid not in focus_fid:
            continue
        setup_text = str(item.get("setup_text") or "")
        payoff_text = str(item.get("payoff_text") or "")
        expected = str(item.get("expected_payoff") or "")
        foreshadowing_detail.append(
            {
                "id": fid or item.get("id"),
                "setup_chapter_no": item.get("setup_chapter_no"),
                "setup_text": _clip(setup_text, 900),
                "expected_payoff": _clip(expected, 520),
                "payoff_chapter_no": item.get("payoff_chapter_no"),
                "payoff_text": _clip(payoff_text, 900),
                "status": item.get("status"),
            }
        )

    world_detail: list[dict[str, Any]] = []
    for e in list(story_context.world_entries or []):
        if not isinstance(e, dict):
            continue
        title = str(e.get("title") or "").strip()
        if title not in world_kws and title not in text:
            continue
        world_detail.append(
            {
                "id": e.get("id"),
                "entry_type": e.get("entry_type"),
                "title": title,
                "content": _clip(str(e.get("content") or ""), 720),
                "metadata_json": e.get("metadata_json") or {},
            }
        )
    world_detail = world_detail[:_MAX_SLICED_WORLD]

    return {
        "meta": {
            "purpose": "server_side_evidence_pack",
            "chapter_no": chapter_no,
        },
        "characters_detail": characters_detail,
        "timeline_detail": timeline_detail,
        "foreshadowing_detail": foreshadowing_detail,
        "world_detail": world_detail,
    }


def collect_review_fetch_allowlist(
    *,
    review_focus: dict[str, Any],
    review_context_slice: dict[str, Any],
    evidence_pack: dict[str, Any],
) -> set[str]:
    """聚合已进入证据包/焦点的实体 id，供一档下 fetch 白名单校验。"""
    ids: set[str] = set()
    for bucket in ("characters", "world_entries", "timeline_events", "foreshadowings"):
        for row in list(review_context_slice.get(bucket) or []):
            if isinstance(row, dict) and row.get("id"):
                ids.add(str(row["id"]).strip())
    for bucket in ("characters_detail", "world_detail", "timeline_detail", "foreshadowing_detail"):
        for row in list(evidence_pack.get(bucket) or []):
            if isinstance(row, dict) and row.get("id"):
                ids.add(str(row["id"]).strip())
    for x in review_focus.get("focus_timeline_event_ids") or []:
        ids.add(str(x).strip())
    for x in review_focus.get("focus_foreshadowing_ids") or []:
        ids.add(str(x).strip())
    return {i for i in ids if i}
