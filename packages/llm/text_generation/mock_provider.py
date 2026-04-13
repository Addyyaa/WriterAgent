from __future__ import annotations

import hashlib
from dataclasses import asdict

from packages.core.utils import ensure_non_empty_string
from packages.llm.text_generation.base import (
    TextGenerationProvider,
    TextGenerationRequest,
    TextGenerationResult,
)


class MockTextGenerationProvider(TextGenerationProvider):
    """确定性 Mock 文本生成器，用于无真实 LLM 条件下的全链路联调。"""

    def __init__(self, model: str = "mock-writer-v1") -> None:
        self.model = model

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        goal = ensure_non_empty_string(request.user_prompt, field_name="user_prompt")
        title = self._build_title(goal)
        content = self._build_content(goal=goal, target_words=self._target_words(request))
        summary = self._build_summary(content)

        payload = {
            "title": title,
            "content": content,
            "summary": summary,
        }
        return TextGenerationResult(
            text=content,
            json_data=payload,
            model=self.model,
            provider="mock",
            is_mock=True,
            raw_response_json={
                "mock": True,
                "request": asdict(request),
                "output": payload,
            },
        )

    @staticmethod
    def _target_words(request: TextGenerationRequest) -> int:
        raw = request.metadata_json.get("target_words")
        if raw is None:
            return 800
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return 800
        return max(200, min(value, 5000))

    @staticmethod
    def _build_title(goal: str) -> str:
        digest = hashlib.md5(goal.encode("utf-8")).hexdigest()[:6]
        return f"第X章·{goal[:18]}（{digest}）"

    @staticmethod
    def _build_content(*, goal: str, target_words: int) -> str:
        sentence = (
            f"围绕“{goal}”，主角推进冲突并触发关键转折，"
            "同时保持人物动机清晰、场景细节可视化、叙事节奏渐进。"
        )
        target_chars = max(600, target_words * 2)
        parts: list[str] = []
        while sum(len(item) for item in parts) < target_chars:
            parts.append(sentence)
        return "\n".join(parts)

    @staticmethod
    def _build_summary(content: str) -> str:
        preview = content.replace("\n", " ").strip()
        return preview[:120] + ("..." if len(preview) > 120 else "")
