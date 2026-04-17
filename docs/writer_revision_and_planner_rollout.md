# Writer 修订链路 + Planner 强合同：交付说明

本文档对应「issue-scoped revision + decision-first bundle + writer/revision 默认强知识合同」的可执行拆分与观测方案。合并后请在 PR 描述中附上 **commit hash**（`git rev-parse HEAD`）。

## PR 粒度（逻辑拆分，可单分支合并）

### PR-1：Revision Context 纯化

- **目标**：修订步 `state` 仅含 issue 驱动块，零起草期 alignment 泄漏。
- **涉及文件**
  - [`packages/workflows/revision/service.py`](../packages/workflows/revision/service.py)：`_normalize_retrieval_bundle` 保留完整 decision 包 + 根级双写；`merged_raw` 仅注入 `revision_chapter` / `consistency_review` / `revision_focus` / `revision_context_slice` / `revision_evidence_pack`，不再 `_snapshot_raw_state`。
- **测试**：[`tests/unit/test_revision_workflow.py`](../tests/unit/test_revision_workflow.py)（回归 Assembler）；可补充对 `retrieval` 根字段断言。

### PR-2：Issue-Scoped Retrieval

- **目标**：按 `issues[].category` union 槽位；修订检索不并入 workflow 宽默认；items 白名单 + 上限。
- **涉及文件**
  - [`packages/workflows/revision/issue_retrieval_policy.py`](../packages/workflows/revision/issue_retrieval_policy.py)：类别 → 槽位 / 优先工具。
  - [`packages/workflows/revision/retrieval_item_filter.py`](../packages/workflows/revision/retrieval_item_filter.py)：items 过滤 + 根字段再 mirror。
  - [`packages/workflows/orchestration/retrieval_loop.py`](../packages/workflows/orchestration/retrieval_loop.py)：`RetrievalLoopRequest.slot_merge_skip_workflow_base`、` _merge_inference_slots(..., skip_workflow_base)`。
  - [`packages/workflows/orchestration/service.py`](../packages/workflows/orchestration/service.py)：` _run_retrieval_loop` 覆盖参数；`_run_revision_step` 接线 issue 槽位与过滤。
  - [`packages/workflows/orchestration/step_input_specs.py`](../packages/workflows/orchestration/step_input_specs.py)：`writer_revision` 的 `RetrievalViewSpec`（compact + `allowed_sources` + `max_items=8`）。
- **测试**：[`tests/unit/test_issue_retrieval_policy.py`](../tests/unit/test_issue_retrieval_policy.py)、[`tests/unit/test_retrieval_loop_service.py`](../tests/unit/test_retrieval_loop_service.py)、[`tests/unit/test_prompt_payload_assembler.py`](../tests/unit/test_prompt_payload_assembler.py)。

### PR-3：Context Bundle 根级决策字段（阶段 1）

- **目标**：`context_bundle` 根对象五段 + `key_facts` 双写；消费端根优先（已实现于 core + assembler）。
- **涉及文件**（此前已落地，本次修订路径与之对齐）
  - [`packages/core/context_bundle_decision.py`](../packages/core/context_bundle_decision.py)
  - [`packages/workflows/orchestration/prompt_payload_assembler.py`](../packages/workflows/orchestration/prompt_payload_assembler.py)
  - [`packages/memory/working_memory/context_builder.py`](../packages/memory/working_memory/context_builder.py)
  - [`packages/workflows/orchestration/retrieval_loop.py`](../packages/workflows/orchestration/retrieval_loop.py)
- **阶段 2**：各消费端与 OpenAPI 显式以根字段为准（后续排期）。

### PR-4：Revision / Writer 链路 Planner Strict + Loose 重试 + 可观测性

- **目标**：对配置的工作流类型默认 `strict_node_knowledge`；strict 校验失败时 **自动 loose 重试一次**，再失败才 mock（若开启）；结构化日志指标。
- **涉及文件**
  - [`packages/workflows/orchestration/runtime_config.py`](../packages/workflows/orchestration/runtime_config.py)：`strict_node_knowledge_workflows`、`effective_strict_node_knowledge`；env `WRITER_PLANNER_STRICT_NODE_KNOWLEDGE`、`WRITER_PLANNER_STRICT_NODE_KNOWLEDGE_WORKFLOWS`（`none`/`off`/`false` 清空列表）。
  - [`packages/workflows/orchestration/planner.py`](../packages/workflows/orchestration/planner.py)：strict → `ResponseSchemaValidationError` → loose 重试；事件日志。
- **测试**：[`tests/unit/test_planner_runtime_strict.py`](../tests/unit/test_planner_runtime_strict.py)。

## 关键指标（日志 JSON `event` 字段）

| event | 含义 |
|--------|------|
| `planner_node_knowledge_strict_ok` | 严格知识 schema 下规划成功 |
| `planner_node_knowledge_strict_schema_failed` | 严格校验失败，将尝试 loose |
| `planner_node_knowledge_loose_retry_success` | loose 重试成功 |
| `planner_node_knowledge_loose_retry_failed` | loose 仍失败（含 errors） |
| `planner_empty_nodes_fallback_mock` | 解析节点为空，走 mock 计划 |
| `planner_fallback_mock` | 非 schema 异常或 loose 后仍失败且允许 mock |

建议在日志采集侧按 `workflow_type`、上述 event 做计数与告警。

## 回退策略

1. **关闭按工作流的默认 strict**：`WRITER_PLANNER_STRICT_NODE_KNOWLEDGE_WORKFLOWS=none`
2. **全局关 strict**：不设 `WRITER_PLANNER_STRICT_NODE_KNOWLEDGE=true` 且清空 workflows 列表
3. **仍失败**：保留 `WRITER_PLANNER_FALLBACK_TO_MOCK_ON_ERROR`（默认 true）作为最后逃生

## 单测清单（相关）

- `tests/unit/test_issue_retrieval_policy.py`
- `tests/unit/test_retrieval_loop_service.py`
- `tests/unit/test_prompt_payload_assembler.py`
- `tests/unit/test_revision_workflow.py`
- `tests/unit/test_planner_runtime_strict.py`
- `tests/unit/test_context_bundle_decision.py`（若存在）
- 全量：`pytest tests/unit/`

## PR 链接

在远程创建 PR 后由作者填写；本地仅记录 `git rev-parse HEAD`。
