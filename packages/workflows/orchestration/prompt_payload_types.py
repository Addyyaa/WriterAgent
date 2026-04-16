"""编排层：LLM 步骤输入规格类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

RetrievalMode = Literal["none", "summary_only", "compact_items", "full_items"]

# 步骤上下文档位：规划（轻量）、生成（摘要 + 可工具拉细节）、严格审查（服务端证据优先）
StepContextTier = Literal["planning", "generative", "strict_review"]


@dataclass
class RetrievalViewSpec:
    """检索上下文进入 prompt 的粒度策略。"""

    mode: RetrievalMode = "summary_only"
    max_items: int = 5
    max_chars_per_item: int = 6000
    allowed_sources: list[str] = field(default_factory=list)


@dataclass
class StateDependencySpec:
    """对前序成功步骤 output_json 的显式依赖。"""

    step_key: str
    required: bool = True
    fields: list[str] = field(default_factory=list)
    from_section: str = "view"
    rename_to: str | None = None
    compact: bool = True


@dataclass
class StepInputSpec:
    """单个 Agent 步骤的输入视图规格。"""

    role_id: str
    include_project: bool = True
    include_outline: bool = True
    include_working_notes: bool = False
    dependencies: list[StateDependencySpec] = field(default_factory=list)
    retrieval: RetrievalViewSpec = field(default_factory=RetrievalViewSpec)
    # Summary-first：与 RetrievalViewSpec 配套，用于日志与策略路由（非强制校验）
    context_tier: StepContextTier = "generative"
