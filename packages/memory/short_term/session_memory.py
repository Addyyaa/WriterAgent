from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class SessionMemorySummary:
    summary: str
    key_facts: list[str] = field(default_factory=list)
    recent_turns: list[str] = field(default_factory=list)
    estimated_tokens: int = 0


class SessionMemoryService:
    """短时记忆压缩器。"""

    _FACT_MARKERS = (
        "是",
        "在",
        "有",
        "发生",
        "计划",
        "目标",
        "禁止",
        "必须",
        "需要",
    )

    def compress(
        self,
        turns: list[ChatTurn | dict[str, Any]],
        *,
        token_budget: int = 600,
        max_facts: int = 8,
        max_recent_turns: int = 8,
    ) -> SessionMemorySummary:
        if token_budget <= 0:
            return SessionMemorySummary(summary="", key_facts=[], recent_turns=[], estimated_tokens=0)

        normalized = self._normalize_turns(turns)
        if not normalized:
            return SessionMemorySummary(summary="", key_facts=[], recent_turns=[], estimated_tokens=0)

        # 最近轮次优先，确保当前对话语境不丢失。
        tail = normalized[-max_recent_turns:]
        recent_texts = [f"{item.role}: {item.content}" for item in tail if item.content]

        facts = self._extract_key_facts(normalized, max_facts=max_facts)

        summary_parts: list[str] = []
        if facts:
            summary_parts.append("关键事实：" + "；".join(facts))
        if recent_texts:
            summary_parts.append("最近对话：" + " | ".join(recent_texts[-4:]))

        summary = "\n".join(summary_parts).strip()
        estimated_tokens = self._estimate_tokens(summary)

        if estimated_tokens > token_budget:
            # 保守截断：优先保留事实，再截断最近对话。
            summary = self._truncate_to_budget(summary, token_budget)
            estimated_tokens = self._estimate_tokens(summary)

        return SessionMemorySummary(
            summary=summary,
            key_facts=facts,
            recent_turns=recent_texts,
            estimated_tokens=estimated_tokens,
        )

    def _normalize_turns(self, turns: list[ChatTurn | dict[str, Any]]) -> list[ChatTurn]:
        out: list[ChatTurn] = []
        for item in turns:
            if isinstance(item, ChatTurn):
                turn = item
            elif isinstance(item, dict):
                role = str(item.get("role") or "user").strip() or "user"
                content = str(item.get("content") or "").strip()
                created_at = item.get("created_at")
                if isinstance(created_at, datetime):
                    dt = created_at
                else:
                    dt = datetime.now(tz=timezone.utc)
                turn = ChatTurn(role=role, content=content, created_at=dt)
            else:
                continue
            if turn.content:
                out.append(turn)
        return out

    def _extract_key_facts(self, turns: list[ChatTurn], *, max_facts: int) -> list[str]:
        facts: list[str] = []
        seen: set[str] = set()

        for turn in turns:
            text = turn.content.strip()
            if not text:
                continue

            candidates = self._split_sentences(text)
            for sentence in candidates:
                if len(sentence) < 8:
                    continue
                if not any(marker in sentence for marker in self._FACT_MARKERS):
                    continue
                normalized = sentence.strip()
                if normalized in seen:
                    continue
                seen.add(normalized)
                facts.append(normalized)
                if len(facts) >= max_facts:
                    return facts

        return facts

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        out: list[str] = []
        buff = ""
        for ch in text:
            buff += ch
            if ch in {"。", "！", "？", ".", "!", "?", "\n"}:
                segment = buff.strip()
                if segment:
                    out.append(segment)
                buff = ""
        if buff.strip():
            out.append(buff.strip())
        return out

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        # 经验估计：中英文混合场景下保守按 2 字符约 1 token。
        return max(1, len(text) // 2) if text else 0

    def _truncate_to_budget(self, text: str, token_budget: int) -> str:
        if not text:
            return ""
        max_chars = max(16, token_budget * 2)
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."
