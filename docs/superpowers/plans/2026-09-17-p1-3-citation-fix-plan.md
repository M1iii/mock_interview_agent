# P1-3 引用准确率修复实施计划（方案 2：读时回查 ES 父块文本）

- 日期：2026-09-17
- 范围：仅 P1-3（引用上卷）；P1-4 另行评估，不纳入本次
- 前置：P1 验收 FAIL 项已按用户裁决落档（p1-acceptance-report.md）；本次为应用缺陷修复

## 1. 背景与目标

### 根因（验收报告 §3.1）
- 验收语料中 Markdown 标题行与正文间有空行 → `chunking._split_paragraphs` 按空行切段 → 标题行成为独立子块（裸标题块），单独向量化入 Qdrant
- `retrieve` 语义路命中子块后，引用文本取 `payload.text`（子块文本）→ 双路合并 `text = sem_hit["text"] or kw_hit["text"]` 优先语义路子块 → 引用文本多为裸标题，无信息量
- LLM 裁判判定"引用不支撑题目" → 实测 cites 18/144 = 12%（标准 ≥90%）

### 目标
引用文本装配从「命中子块文本」改为「按 parent_id 回查 ES 取父块全文（标题 + 正文）」，使引用片段包含可支撑题目的正文内容；ES 回查失败时回退子块文本，不阻断出题。

## 2. 已确认决策（2026-09-17 用户裁决）

| 决策点 | 结论 |
|---|---|
| 修复范围 | 仅 P1-3；P1-4（decline 不可达）另行评估 |
| 实现路线 | 方案 2：检索时按 parent_id 回查 ES 父块文本（零存储冗余、单一数据源、存量库免重建） |
| 回查失败兜底 | 回退子块文本（引用始终存在，行为与现状一致），日志记 warning |
| 引用片段截断 | `_SNIPPET_LEN` 120 → 200（仅影响 LLM prompt 侧；前端展示侧本就渲染完整 c.text，零改动） |

## 3. 改动点

### 3.1 `app/retrieval/retrieve.py`（核心）

新增私有函数 `_backfill_parent_text(semantic_hits: dict[str, dict], es: ESManager) -> None`：

```python
def _backfill_parent_text(semantic_hits, es):
    """语义路命中后按 parent_id 回查 ES 父块全文（方案 2）；失败回退子块文本。"""
    try:
        client = es.get_client()
        resp = client.mget(index=es.index, ids=list(semantic_hits), _source=["text"])
    except Exception as e:  # noqa: BLE001 - 回查失败仅回退，不阻断
        logger.warning("parent text backfill failed, fallback to child text: {err}", err=repr(e))
        return
    for doc in resp.get("docs", []):
        pid = doc.get("_id")
        src = doc.get("_source") or {}
        if pid in semantic_hits and src.get("text"):
            semantic_hits[pid]["text"] = src["text"]
```

在 `retrieve()` 语义路命中收集完成后、`_merge_hits` 合并前调用：

```python
if semantic_hits:
    _backfill_parent_text(semantic_hits, es)
```

要点：
- `es.get_client()` 内部走 `is_available()`，ES 不可用抛 `RetrievalUnavailable` → 被 except 捕获 → 整体回退子块文本（与「ES 挂、语义路存活」场景吻合）
- mget 一次取回 ≤top_k 个 parent_id 的父块文本，本地 ES 耗时约 1-3ms，计入 `total_ms`（P1-6 有 134ms/2000ms 富余）
- 文本替换后，`_merge_hits` 无需改动：双路命中 `sem_hit["text"] or kw_hit["text"]` 两边同源（同一 parent_id 的 ES 父块 doc），单路语义直接用回查后的父块文本
- 分数 / 分级 / 排序逻辑完全不动（回查只影响展示文本）

### 3.2 `app/interview/nodes/__init__.py`

- `_SNIPPET_LEN = 120` → `200`（仅 `_build_reference_block` prompt 侧截断）
- `_build_reference_block` / `_citation_dict` 逻辑不变（c.text 现在为父块全文，自动受益）
- 前端与评估节点零改动（`_citations` 透传既有机制）

### 3.3 前端

零改动。`web/src/views/ChatView.vue` 引用面板渲染完整 `c.text`，父块文本下发后展示自动包含标题+正文。

## 4. 测试计划

### 4.1 新增用例（tests/test_retrieval_retrieve.py）

1. `test_retrieve_semantic_uses_parent_text`：语义路命中 → `citations[0].text` = mget 回查的父块文本（≠ 子块文本）
2. `test_retrieve_backfill_falls_back_on_mget_error`：ES 可用但 mget 抛异常 → 引用文本 = 子块文本，引用仍存在
3. `test_retrieve_backfill_falls_back_on_missing_doc`：mget 返回缺该 parent_id → 回退子块文本
4. `test_retrieve_double_hit_text_is_parent`：双路命中 → text 为父块文本（与关键词路同源）

### 4.2 更新既有用例

- `_es_mock` 增加 `mget` 默认 mock（按 ids 返回 `{"docs": [{"_id": pid, "_source": {"text": f"父块-{pid}"}}]}`）
- 手写 es mock 的用例（`test_retrieve_fallback_only_semantic`、`test_retrieve_respects_top_k` 等）补 mget mock
- `test_retrieve_es_unavailable_degrades_to_semantic` 天然覆盖"回查失败回退"路径，追加 `citations[0].text == "内容A"` 断言
- `_merge_hits` 单元测试不动（dict 结构不变）

### 4.3 回归

- 全量 pytest（当前 218 例 + 新增）
- `uv run ruff format app/ tests/` + lint
- 前端 `npm run build`（确认零改动不破坏构建）

## 5. 验收复测口径（P1-3）

1. 重建验收库：5 篇 MD 语料 + 50 题题库重新入库（`_acceptance_p1.py` 自带入库流程）
2. `uv run python _acceptance_p1.py`（全量串行，含 P1-2/P1-6 回归确认父块文本变更无副作用）
3. 判定标准不变：P1-3 引用准确率 ≥90% 且 judged≥40
4. 通过 → 更新验收报告 P1-3 行与归因 → 更新 project-status / PRD / CHANGELOG

## 6. 文档落档（CHANGELOG 格式遵循项目惯例）

- 日期 + 标题 + 描述（P1-3 引用上卷修复）+ 改动清单 + 验证结果（复测指标 + pytest 数）+ 项目结构更新（无新增文件时注明）

## 7. 风险与边界

- ES 不可用：关键词路跳过 + 回查回退 → 行为与现状完全一致，不阻断
- 引用条数：父块去重后 citations 可能 < MAX_CITATIONS=3，前端按实际数量渲染，无影响
- 存量知识库：本方案零迁移（回查逻辑对新旧数据同时生效）
- 不做：P1-4 修复、切块层标题合并（方案 B）、标题块识别（仅对标题牵引）——均不纳入本次
