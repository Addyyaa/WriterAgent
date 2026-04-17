from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, replace

from packages.llm.prompt_audit import record_llm_prompt_audit
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
        llm_task_id = str(uuid.uuid4())
        request = replace(
            request,
            metadata_json={**dict(request.metadata_json or {}), "llm_task_id": llm_task_id},
        )
        record_llm_prompt_audit(
            llm_task_id=llm_task_id,
            system_prompt=str(request.system_prompt or ""),
            user_prompt=str(request.user_prompt or ""),
            model=self.model,
            provider_label="MockTextGenerationProvider",
            metadata=dict(request.metadata_json or {}),
            prompt_guard_applied=False,
        )
        fn = str(request.function_name or "").lower()
        if "consistency" in fn:
            return self._generate_consistency_mock(request)
        if fn == "outline_generation_output":
            return self._generate_outline_mock(request)

        goal = self._resolve_goal(request)
        title = self._build_title(goal)
        content = self._build_content(goal=goal, target_words=self._target_words(request))
        summary = self._build_summary(content)

        payload = {
            "mode": "draft",
            "status": "success",
            "segments": [],
            "word_count": len(content),
            "notes": "",
            "chapter": {
                "title": title,
                "content": content,
                "summary": summary,
            },
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
            request_metadata_json=dict(request.metadata_json or {}),
        )

    def _generate_outline_mock(self, request: TextGenerationRequest) -> TextGenerationResult:
        """与 OutlineGenerationWorkflowService 输出 schema 对齐的 mock。"""
        goal = self._resolve_goal(request)
        title = self._build_title(goal)
        synopsis = (
            f"[Mock 大纲梗概] 围绕目标推进：{goal[:120].replace('\n', ' ')}。"
            "关键转折与章末钩子为占位；不得视为正文。"
        )
        payload = {
            "title": title,
            "content": synopsis,
            "structure_json": {
                "chapter_goal": goal[:500],
                "core_conflict": "[Mock] 核心矛盾占位",
                "end_hook": "[Mock] 章末钩子占位",
                "must_preserve_facts": [],
                "open_questions": [],
                "assumptions_used": [],
                "acts": [
                    {
                        "name": "第一幕",
                        "chapter_targets": [goal[:200] or "本章目标"],
                        "risk_points": [],
                    }
                ],
                "character_arcs": [],
                "foreshadowing_plan": [],
            },
        }
        return TextGenerationResult(
            text=json.dumps(payload, ensure_ascii=False),
            json_data=payload,
            model=self.model,
            provider="mock",
            is_mock=True,
            raw_response_json={"mock": True, "output": payload},
            request_metadata_json=dict(request.metadata_json or {}),
        )

    def _generate_consistency_mock(self, request: TextGenerationRequest) -> TextGenerationResult:
        payload = {
            "overall_status": "warning",
            "audit_summary": "[Mock] 基于规则引擎的基础审查已完成，LLM 深层审查处于模拟模式。",
            "issues": [
                {
                    "category": "character",
                    "severity": "warning",
                    "evidence_context": "[Mock] 无法获取真实上下文比对",
                    "evidence_draft": "[Mock] 无法获取真实草稿比对",
                    "reasoning": "当前为 Mock 模式，无法进行真实的一致性检查。请配置真实 LLM 以获得有效审查结果。",
                    "revision_suggestion": "设置 WRITER_LLM_USE_MOCK=0 并配置有效的 LLM API，然后重新运行一致性审校。",
                }
            ],
        }
        return TextGenerationResult(
            text=json.dumps(payload, ensure_ascii=False),
            json_data=payload,
            model=self.model,
            provider="mock",
            is_mock=True,
            raw_response_json={"mock": True, "output": payload},
            request_metadata_json=dict(request.metadata_json or {}),
        )

    @staticmethod
    def _resolve_goal(request: TextGenerationRequest) -> str:
        goal_keys = ("goal", "writing_goal", "task")
        payload = request.input_payload
        if isinstance(payload, dict):
            for key in goal_keys:
                value = str(payload.get(key) or "").strip()
                if value:
                    return value

        raw_prompt = str(request.user_prompt or "").strip()
        if raw_prompt.startswith("{"):
            try:
                parsed = json.loads(raw_prompt)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                for key in goal_keys:
                    value = str(parsed.get(key) or "").strip()
                    if value:
                        return value

        if len(raw_prompt) > 200:
            return raw_prompt[:200]
        return raw_prompt or "mock writing goal"

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
        short = goal[:18].replace("\n", " ")
        return f"[Mock] {short} ({digest})"

    @staticmethod
    def _build_content(*, goal: str, target_words: int) -> str:
        safe_goal = goal[:40].replace("\n", " ")
        paragraphs = [
            f"天色微暗，城市的轮廓在薄雾中若隐若现。关于「{safe_goal}」的故事在此刻悄然展开。",
            "主角站在街角，深吸一口气，感受到体内某种沉睡已久的力量正在苏醒。那是一种难以言喻的感觉——仿佛世界的运转规则在他眼中变得清晰可见。",
            "「你终于醒了。」身后传来一个低沉的声音，带着几分不耐烦，却又藏着深深的期待。主角猛然回头，看到一个身着灰色风衣的陌生人正靠在墙上，嘴角挂着似笑非笑的弧度。",
            "「你是谁？」主角警惕地后退一步。",
            "「这不重要。重要的是，你现在拥有的能力——它既是礼物，也是诅咒。」陌生人直起身子，目光锐利如刀，「而你将要面对的困境，远比你想象的要严酷。」",
            "话音未落，远处传来一声低沉的轰鸣。地面微微震颤，街灯开始闪烁。主角感到一股巨大的压迫感从四面八方涌来，像是有什么庞然大物正在接近。",
            "危机来得比预想的更快。主角来不及多想，本能地调动刚刚觉醒的力量。一道微弱但坚定的光芒从掌心浮现，将周围的黑暗撕开一道口子。",
            "陌生人退后几步，眼中闪过一丝赞许：「不错，但还远远不够。记住——力量的真正用途，不是战斗，而是选择。」",
            f"在这一刻，关于「{safe_goal}」的旅程才真正开始。前方的道路充满未知，而主角已经踏出了不可回头的第一步。",
            "街灯在夜色中摇曳，远处传来隐约的钟声。主角抬头望向天际，一颗流星划过厚重的云层，仿佛在预示着什么。身后的陌生人已经消失无踪，只留下一阵若有似无的风。",
            "主角握紧拳头，掌心的光芒逐渐稳定。他知道，从这一刻起，自己的命运已经彻底改变。无论前方等待着什么，都不能回头了。",
            "城市的喧嚣渐渐远去，主角踏上了一条从未走过的路。黑暗中，那股新生的力量如同心跳一般稳定地脉动着，指引着前行的方向。",
        ]
        parts: list[str] = list(paragraphs)
        return "\n\n".join(parts)

    @staticmethod
    def _build_summary(content: str) -> str:
        preview = content.replace("\n", " ").strip()
        return preview[:120] + ("..." if len(preview) > 120 else "")
