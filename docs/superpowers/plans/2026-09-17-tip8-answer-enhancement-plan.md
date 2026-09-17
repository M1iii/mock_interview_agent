# Tip 8：答案增强（评估节点复发出题检索结果）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 评估节点复发出题时的检索结果，实现「知识库优先，自身知识兜底」的答案增强评估，评语标注引用角标，右侧评估面板展示引用来源折叠列表。

**Architecture:** 检索仍只在出题节点发生（保持「仅出题注入」原则），出题节点将参考资料文本 + 引用元数据存入 state；评估节点从 state 读取并注入 prompt，按「知识库优先」原则评估并在评语中标注角标；SSE assess 事件携带引用元数据，前端评估面板新增来源折叠。无知识库 / decline 级完全退化为纯 LLM 评估。

**Tech Stack:** Python / FastAPI / LangGraph / Vue 3 / TypeScript

---

## 文件结构

| 文件 | 操作 | 职责 |
|---|---|---|
| `app/interview/state.py` | 修改 | Score 新增 `citations` 字段；state 新增 `_reference_block`（运行时注入） |
| `app/interview/nodes/__init__.py` | 修改 | ask_question_node 写 `_reference_block`；evaluate_node 读 `_reference_block` 并写 `score.citations` |
| `app/interview/prompts/evaluate.py` | 修改 | 新增 `{reference_block}` 占位 + 知识库优先评估指令 + 角标标注要求 |
| `app/api/chat.py` | 修改 | assess 事件载荷新增 `citations` 字段 |
| `web/src/api/types.ts` | 修改 | AssessPayload 新增 `citations?: Citation[]` |
| `web/src/views/ChatView.vue` | 修改 | 评估面板新增引用来源折叠区（与题干来源折叠样式一致） |
| `tests/test_nodes.py` | 修改 | 新增评估注入测试：normal/weak 注入、fallback 弱提示、decline 纯通用、无 kb 纯通用、score.citations 写入 |
| `tests/test_stream_integration.py` | 修改 | 新增 assess 事件携带 citations 的断言 |
| `CHANGELOG.md` | 修改 | 追加 Tip 8 条目 |
| `docs/project-status.md` | 修改 | §4 追加完成项 / §6.6 Tip 8 标记完成 / §8 追加决策日志 |

---

### Task 1：状态扩展（Score.citations + _reference_block）

**Files:**
- Modify: `app/interview/state.py:9-17, 39-46`
- Test: `tests/test_state.py`（验证 Score 默认值 + TypedDict 结构）

- [ ] **Step 1: 修改 Score，新增 citations 字段**

```python
class Score(TypedDict, total=False):
    """单题评分记录。"""

    question: str
    answer: str
    score: float
    comment: str
    dimensions: dict[str, float]
    citations: list[dict]  # P1 Tip 8：本题引用元数据（评估面板 & 报告展示用）
```

- [ ] **Step 2: 修改 InterviewState，新增 _reference_block 运行时字段**

在 `_citations` 行上方或下方追加：

```python
    _reference_block: str  # 当前题参考资料文本（出题节点写入，评估节点复用）
```

- [ ] **Step 3: 运行现有 state 测试，确认无回归**

Run: `uv run pytest tests/test_state.py -v`
Expected: 4 passed

---

### Task 2：出题节点写 _reference_block

**Files:**
- Modify: `app/interview/nodes/__init__.py:96-149`
- Test: `tests/test_nodes.py`（已有出题注入测试，补 `_reference_block` 断言）

- [ ] **Step 1: 修改 ask_question_node，将 reference_block 写入 state**

在 `updates` dict 中新增一行（与 `_citations` 同级）：

```python
    if citations:
        updates["_citations"] = citations
        updates["_reference_block"] = reference_block
    return updates
```

- [ ] **Step 2: 在已有出题注入测试中补 _reference_block 断言**

找到 `test_ask_question_normal_weak_injects`，在 result 断言后追加：

```python
    assert result["_reference_block"]
    assert "【参考资料】" in result["_reference_block"]
    assert "[1]" in result["_reference_block"]
```

找到 `test_ask_question_decline_pure` 和 `test_ask_question_no_kb_pure_generic`，追加：

```python
    assert "_reference_block" not in result
```

- [ ] **Step 3: 运行出题节点测试确认通过**

Run: `uv run pytest tests/test_nodes.py -k "ask_question" -v`
Expected: 全部通过

---

### Task 3：评估 prompt 改造

**Files:**
- Modify: `app/interview/prompts/evaluate.py`
- Test: （节点测试覆盖，见 Task 4）

- [ ] **Step 1: 重写 EVALUATE 模板，新增参考资料区块 + 知识库优先规则**

```python
EVALUATE = """\
你是「AI 面试官」，请评估候选人的回答。

【面试场景】{scene}
【当前题目】{current_question}
【候选人回答】{candidate_answer}

{reference_block}

四维评分（每维 0-10 分）：
- 技术深度：概念理解与原理掌握程度
- 表达清晰度：逻辑条理与语言组织
- 问题解决：分析思路与方案设计能力
- 项目经验：实战描述与经验反思

评估规则：
- 实习场景：基础概念正确即"技术深度"达标，不要求底层原理
- 全职场景：需体现原理理解和系统性思考
- 有参考资料时：优先基于参考资料评估事实准确性；参考资料未覆盖的部分，基于你的专业知识评估
- 有参考资料时：评语中若引用了某条资料的观点或指出与资料不符之处，请标注对应角标，\
例如：缓存穿透的解决方案描述准确[1] / 缓存击穿的解释与资料不符[2]

请判断是否需要追问：
- 回答不充分 / 有深挖空间 → 需要追问
- 回答到位 / 无深挖必要 → 无需追问

输出格式：
{{"score": {{"技术深度": x, "表达清晰度": x, "问题解决": x, "项目经验": x}}, \
"comment": "简要评语", "needs_followup": true/false, "followup_reason": "追问原因（如需追问时填）"}}\
"""  # noqa: E501
```

- [ ] **Step 2: 确认 reference_block 空字符串时完全退化**

验证：当 `reference_block=""` 时，prompt 中会出现一行空行（`\n\n`），不影响 LLM 输出格式——这是可接受的（与出题 prompt 的处理方式一致）。

---

### Task 4：评估节点读 _reference_block 并写 score.citations

**Files:**
- Modify: `app/interview/nodes/__init__.py:152-190`
- Test: `tests/test_nodes.py`（新增 5 例评估注入测试）

- [ ] **Step 1: 先写失败测试——新增 5 个评估注入用例**

在 `tests/test_nodes.py` 末尾追加：

```python
from app.retrieval.retrieve import NORMAL, WEAK, FALLBACK, DECLINE


def _make_citations(n=3):
    return [
        {"file_name": f"doc{i}.md", "text": f"参考内容 {i}", "score": 0.9 - i * 0.1}
        for i in range(1, n + 1)
    ]


def test_evaluate_normal_injects_reference():
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "请解释缓存穿透"
    state["_reference_block"] = "【参考资料】\n[1]《redis.md》：缓存穿透指查询不存在的数据..."
    state["_citations"] = _make_citations(2)
    llm = _make_llm(
        '{"score": {"技术深度": 8, "表达清晰度": 7, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答准确，与资料一致[1]", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    # 确认 LLM 收到的 prompt 包含参考资料
    call_prompt = llm.complete_sync.call_args[1]["prompt"]
    assert "【参考资料】" in call_prompt
    assert "[1]" in call_prompt
    # 确认 score 写入 citations
    scores = result["scores"]
    assert len(scores) == 1
    assert scores[0]["citations"] == state["_citations"]
    assert "[1]" in scores[0]["comment"]


def test_evaluate_fallback_injects_with_note():
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是分布式事务"
    state["_reference_block"] = (
        "【参考资料】\n[1]《misc.md》：一些零散内容\n"
        "注意：以下资料与本次面试主题相关性有限，仅作参考，题目仍应考察通用知识。"
    )
    state["_citations"] = _make_citations(1)
    llm = _make_llm(
        '{"score": {"技术深度": 6, "表达清晰度": 7, "问题解决": 6, "项目经验": 5}, '
        '"comment": "回答基本正确", "needs_followup": true, "followup_reason": "可深入"}'
    )
    result = evaluate_node(state, llm)
    call_prompt = llm.complete_sync.call_args[1]["prompt"]
    assert "相关性有限" in call_prompt
    assert len(result["scores"]) == 1
    assert len(result["scores"][0]["citations"]) == 1


def test_evaluate_decline_pure_generic():
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是 RESTful"
    # 无 _reference_block / _citations（decline 时出题节点不写）
    llm = _make_llm(
        '{"score": {"技术深度": 7, "表达清晰度": 8, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答清晰", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    call_prompt = llm.complete_sync.call_args[1]["prompt"]
    assert "【参考资料】" not in call_prompt
    # decline 时不写 citations 到 score
    assert "citations" not in result["scores"][0]


def test_evaluate_no_kb_pure_generic():
    state = initial_state()  # 无 kb_id
    state["_api_key"] = "sk-test"
    state["current_question"] = "介绍一下你的项目"
    # 无 _reference_block
    llm = _make_llm(
        '{"score": {"技术深度": 7, "表达清晰度": 8, "问题解决": 7, "项目经验": 7}, '
        '"comment": "项目经验丰富", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    call_prompt = llm.complete_sync.call_args[1]["prompt"]
    assert "【参考资料】" not in call_prompt
    assert "citations" not in result["scores"][0]


def test_evaluate_citations_match_topic():
    """评估节点原样传递出题节点的 citations（不做重新检索）。"""
    state = initial_state()
    state["_api_key"] = "sk-test"
    state["current_question"] = "什么是缓存雪崩"
    cites = [{"file_name": "redis.md", "text": "雪崩...", "score": 0.85}]
    state["_reference_block"] = "【参考资料】\n[1]《redis.md》：缓存雪崩指大量 Key 同时失效..."
    state["_citations"] = cites
    llm = _make_llm(
        '{"score": {"技术深度": 7, "表达清晰度": 7, "问题解决": 7, "项目经验": 6}, '
        '"comment": "回答基本正确[1]", "needs_followup": false, "followup_reason": ""}'
    )
    result = evaluate_node(state, llm)
    assert result["scores"][0]["citations"] is cites  # 同一引用（不重新检索）
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/test_nodes.py -k "evaluate_" -v`
Expected: 新增的 5 个测试失败（因为 evaluate_node 还没读 _reference_block、还没写 citations）

- [ ] **Step 3: 修改 evaluate_node 实现**

将 `evaluate_node` 改为：

```python
def evaluate_node(state: InterviewState, llm: DeepSeekClient) -> dict:
    """评估：LLM 打分 + 判断是否追问。

    有知识库参考资料时（出题节点检索命中），注入 prompt 实现知识库优先评估；
    无资料时完全退化为纯 LLM 评估。
    """
    scene = state.get("scene", "fulltime")
    answer = _extract_answer(state)
    reference_block = state.get("_reference_block", "")
    prompt = EVALUATE.format(
        scene=scene,
        current_question=state.get("current_question", ""),
        candidate_answer=answer,
        reference_block=reference_block,
    )
    raw, _ = llm.complete_sync(api_key=state["_api_key"], prompt=prompt)
    try:
        parsed = json.loads(raw)
        score_dict = parsed.get("score", {})
        comment = parsed.get("comment", "")
        needs_followup = parsed.get("needs_followup", False)
        followup_reason = parsed.get("followup_reason", "")
    except json.JSONDecodeError, TypeError:
        score_dict = {}
        comment = raw
        needs_followup = False
        followup_reason = ""
    score_entry: Score = {
        "question": state.get("current_question", ""),
        "answer": answer,
        "score": sum(score_dict.values()) / len(score_dict) if score_dict else 0,
        "comment": comment,
        "dimensions": score_dict,
        "topic": state.get("_topic", ""),
    }
    # 有参考资料时，把引用元数据写入 score（供评估面板 & 报告展示）
    citations = state.get("_citations")
    if citations:
        score_entry["citations"] = citations
    new_scores = [*state.get("scores", []), score_entry]
    # 不需要追问时推进题号（进入下一题或进 report）
    updates = {
        "scores": new_scores,
        "_needs_followup": needs_followup,
        "_followup_reason": followup_reason,
    }
    if not needs_followup:
        updates["question_index"] = state.get("question_index", 0) + 1
    return updates
```

- [ ] **Step 4: 运行评估节点测试确认通过**

Run: `uv run pytest tests/test_nodes.py -k "evaluate_" -v`
Expected: 全部通过（原 3 例 + 新 5 例 = 8 例）

- [ ] **Step 5: 跑全量节点测试确认无回归**

Run: `uv run pytest tests/test_nodes.py -v`
Expected: 全部通过

---

### Task 5：SSE assess 事件携带 citations

**Files:**
- Modify: `app/api/chat.py:405-417`
- Test: `tests/test_stream_integration.py`（补 assess 事件含 citations 的断言）

- [ ] **Step 1: 修改 assess 事件载荷**

在 `yield _sse_event("assess", ...)` 的 dict 中新增：

```python
                                "citations": last.get("citations", []),
```

- [ ] **Step 2: 补流式集成测试——assess 事件携带 citations**

在 `tests/test_stream_integration.py` 中找到 `test_answer_emits_assess_event`，在断言 `assess` 事件后追加 citations 断言（先确认当前测试是否设置了 citations 场景；如果没有，需新增一个带 kb + 检索的集成测试，或者在现有测试的 mock 中构造 citations 场景）。

具体做法：在现有 `test_answer_emits_assess_event` 测试中，在图调用前给 state 注入 `_citations`（模拟出题节点已检索命中），然后断言 assess 事件含 citations。

如果测试构造较复杂，可以改为：新增一个测试 `test_assess_event_includes_citations_when_present`，直接构造一个有 citations 的 score，验证 assess 事件透传。

- [ ] **Step 3: 运行流式集成测试确认通过**

Run: `uv run pytest tests/test_stream_integration.py -v`
Expected: 全部通过

---

### Task 6：前端类型 + 评估面板引用折叠

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/views/ChatView.vue`
- Test: `npm run build` 验证

- [ ] **Step 1: 修改 AssessPayload，新增 citations 字段**

在 `types.ts` 中找到 `AssessPayload`，新增：

```typescript
export interface AssessPayload {
  dimensions: Record<string, number>
  comment: string
  score: number
  citations?: Citation[]  // Tip 8：本题引用元数据，评估面板展示来源折叠
}
```

- [ ] **Step 2: 修改 ChatView，assess 事件接收 citations**

在 `handleEvent` 的 `assess` 分支中，把 citations 传给 `assessData`：

```typescript
  } else if (e.event === 'assess') {
    assessData.value = {
      dimensions: e.dimensions,
      comment: e.comment,
      score: e.score,
      citations: e.citations || [],
    }
```

- [ ] **Step 3: 评估面板新增引用来源折叠区**

在评估面板 `.assess-comment` 下方，参考题干气泡下方的 cite-block 结构，新增：

```vue
            <div
              v-if="hasAssess && assessData!.citations && assessData!.citations.length"
              class="cite-block assess-cites"
            >
              <button class="cite-toggle" @click="showAssessCites = !showAssessCites">
                <span class="cite-arrow" :class="{ open: showAssessCites }">▸</span>
                引用来源（{{ assessData!.citations.length }}）
              </button>
              <div v-if="showAssessCites" class="cite-list">
                <div
                  v-for="(c, ci) in assessData!.citations"
                  :key="ci"
                  class="cite-item"
                >
                  <span class="cite-badge">[{{ ci + 1 }}]</span>
                  <div class="cite-body">
                    <div class="cite-file">{{ c.file_name }}</div>
                    <div class="cite-text">{{ c.text }}</div>
                  </div>
                </div>
              </div>
            </div>
```

在 `<script setup>` 中新增响应式变量：

```typescript
const showAssessCites = ref(false)
```

- [ ] **Step 4: 样式微调（.assess-cites 复用 .cite-block 样式）**

评估面板内的 cite-block 可能需要微调宽度/字号（面板比气泡窄）。在 ChatView 的 `<style>` 中追加：

```css
.assess-cites {
  margin-top: 8px;
  border-top: 1px solid var(--border-light);
  padding-top: 8px;
}
.assess-cites .cite-text {
  font-size: 12px;
  line-height: 1.5;
}
```

- [ ] **Step 5: 前端构建验证**

Run: `cd web ; npm run build`
Expected: build 成功，无 TypeScript 错误

---

### Task 7：全量验证 + 文档落档

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/project-status.md`

- [ ] **Step 1: 全量 pytest**

Run: `uv run pytest -q`
Expected: ~216 passed（211 + 新增 ~5 例）

- [ ] **Step 2: ruff 检查**

Run: `uv run ruff check app/ tests/`
Expected: All checks passed

- [ ] **Step 3: 前端 build**

Run: `cd web ; npm run build`
Expected: 构建成功

- [ ] **Step 4: CHANGELOG 追加 Tip 8 条目**

在 CHANGELOG 顶部新增一条，格式对齐 Tip 7：
- 标题：`## 2026-09-17 · P1 步骤 8（答案增强·评估节点复发出题检索结果）完成`
- 描述：方案 A（复发出题检索结果，不新增检索调用）+ 取向 1（知识库优先，自身知识兜底）+ 四级降级 + 评语角标 + 评估面板引用折叠
- 变更内容：state 扩展 / 出题写 reference_block / 评估读 reference_block + 写 score.citations / 评估 prompt 改造 / SSE assess 事件带 citations / 前端评估面板来源折叠
- 验证结果：pytest / ruff / 前端 build 数量
- 项目结构更新：列出修改文件

- [ ] **Step 5: project-status.md 更新三处**
  - §4 已完成事项：追加 Tip 8 完成行
  - §6.6 P1 分步执行计划：Tip 8 标记为 ✅ 已完成，补充描述
  - §8 决策日志：追加 Tip 8 决策（复发出题检索 + 取向 1 知识库优先）
