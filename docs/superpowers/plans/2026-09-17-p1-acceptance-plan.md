# P1 验收（P1-1 ~ P1-7 真实环境）执行计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在真实服务（Qdrant + ES + TEI + DeepSeek）上验收 P1-1~P1-7 七项退出标准，产出可复现的独立验收脚本 `_acceptance_p1.py` 与验收报告。

**Architecture:** 自建 5 篇多栈 MD 语料（50+ 考点）预标「标准出处块」→ 独立脚本 `_acceptance_p1.py` 串行执行七项验收：入库成功率 → 召回命中率（Top-5 含 gold 块）→ 引用准确率（真实 LLM 出题 + LLM 判定引用支撑性）→ 四级降级路径（真实双路 + 单路 stub 注入）→ 删除级联（三处清零）→ 检索 P95（与召回共用耗时数据）→ Embedding 切换重建（rebuild + 绑定一致）。验收库用时间戳 ID 隔离，结束清理。

**Tech Stack:** Python 3（langchain 既有依赖）、Qdrant、Elasticsearch 7.17（ik）、TEI（bge-large-zh-v1.5）、DeepSeek API、pytest（仅跑既有单测回归）。

**环境前提（执行前确认）**
- Qdrant `http://127.0.0.1:6333/healthz` → 200（已确认）
- ES `http://127.0.0.1:9200/_cluster/health` → 200（已确认）
- TEI `http://127.0.0.1:8081/health` + `POST /v1/embeddings` → 200（已确认）
- `.env` 已配置真实 `LLM_API_KEY`（sk- 前缀，已确认）
- 沙箱禁止 git 写操作（Tip 8 已验证）：**不执行 git add/commit**，逐任务用「工作区快照 + `git diff --no-index`」做 review（沿用 Tip 8 台账裁决）

**验收判定口径（2026-09-17 需求澄清确认）**
- 语料：自建多栈 MD（redis/mysql/java-concurrency/network/os 各 10 考点）
- 判定：预标出处 + 自动化判定——每题在 `questions.json` 记 `gold_snippet`（标准出处块文本唯一片段），入库后经 ES `match_phrase` 定位 `gold_parent_id`
- P1-3：真实 LLM 出题（50 题串行）+ 真实 LLM 判定引用支撑性（每条引用 true/false）
- 脚本形态：独立脚本 `_acceptance_p1.py`（CLI `--only p1-1|...|p1-7|all`，输出结构化报告）

**验收标准对照（PRD §6）**
| 项 | 标准 | 判定 |
|---|---|---|
| P1-1 | 入库成功率 ≥95% | 5/5 文件 ready（含幂等重跑） |
| P1-2 | 50 题 Top-K=5 召回命中率 ≥80% | gold_parent_id ∈ citations |
| P1-3 | normal 级引用准确率 ≥90% | LLM 判定「引用支撑题面」为 true 的比例 |
| P1-4 | 四级降级路径正确 | normal/weak/fallback/decline 各路径断言 |
| P1-5 | 删除级联 0 命中 | Qdrant/ES 按 kb_id+file_id 计数为 0 |
| P1-6 | 单次检索 P95 ≤2s | 50 题 total_ms 采样 P95 |
| P1-7 | 切换重建 + 绑定一致 | rebuild 后绑定更新、检索正常；「查询拒绝校验」未实现 → 观察项 |

**已知缺口（验收观察项，不阻塞）**：architecture v0.4 §4.3「查询模型 ≠ 库绑定模型时拒绝」在检索链路未实现（仅入库/重建时写 binding）。P1-7 验收记录该缺口，不补实现（超出验收范围，交用户裁决）。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `tests/acceptance/corpus/redis.md` 等 5 篇 | 验收语料（每篇 10 考点，父块粒度） |
| `tests/acceptance/questions.json` | 50 题（query + gold_snippet 预标出处） |
| `_acceptance_p1.py` | 独立验收脚本（七项串行 + 报告） |
| `docs/acceptance/p1-acceptance-report.md` | 验收报告（脚本自动生成，人工审阅落档） |
| `docs/project-status.md` / `CHANGELOG.md` / `docs/prd.md` | 验收结论落档 |

注：`tests/acceptance/` 仅含 .md/.json，不会被 pytest 收集（不匹配 `test_*.py`）。

---

### Task 1: 验收语料 + 题库（预标出处）

**Files:**
- Create: `tests/acceptance/corpus/redis.md`
- Create: `tests/acceptance/corpus/mysql.md`
- Create: `tests/acceptance/corpus/java-concurrency.md`
- Create: `tests/acceptance/corpus/network.md`
- Create: `tests/acceptance/corpus/os.md`
- Create: `tests/acceptance/questions.json`

- [ ] **Step 1: 编写 5 篇语料 MD**

每篇用 Markdown 二级标题（`##`）组织考点，一个考点一个段落（父块按段落聚合，子块自动切分）。每段首句必须是该考点标准答案的**要点句**（`gold_snippet` 从首句摘录，保证唯一）。

考点清单（每篇 10 个 `##` 考点）：

- `redis.md`：缓存穿透、缓存击穿、缓存雪崩、RDB 持久化、AOF 持久化、过期删除策略、内存淘汰策略、分布式锁、主从复制、Redis 集群分片
- `mysql.md`：B+ 树索引、聚簇与非聚簇索引、索引失效场景、事务 ACID、隔离级别、锁与死锁、EXPLAIN 执行计划、慢查询优化、分库分表、主从复制与读写分离
- `java-concurrency.md`：线程生命周期、volatile 可见性、synchronized 锁升级、AQS 原理、CAS 与 ABA、线程池参数与拒绝策略、ThreadLocal 与内存泄漏、并发容器、CountDownLatch 与 CyclicBarrier、死锁条件与排查
- `network.md`：三次握手与四次挥手、TIME_WAIT、滑动窗口与流量控制、拥塞控制、HTTP 与 HTTPS、TLS 握手、HTTP/1.1 与 HTTP/2、输入 URL 到渲染、DNS 解析、WebSocket 与轮询
- `os.md`：进程线程协程、进程调度算法、死锁四个条件、虚拟内存与分页、页面置换算法、进程间通信、用户态与内核态、零拷贝、IO 多路复用、孤儿进程与僵尸进程

每个考点段 2-4 句（约 60-150 字），内容准确、术语明确。示例（`redis.md` 首段，其余 49 段按同规范撰写）：

```markdown
# Redis 面试知识

## 缓存穿透

缓存穿透指查询不存在的数据导致请求直接打到数据库，可通过布隆过滤器拦截不存在 Key 和缓存空值（短 TTL）两种方案解决。布隆过滤器有误判率，空值缓存需防止恶意 Key 打满内存。
```

- [ ] **Step 2: 编写 questions.json（50 题）**

每题一个对象，`query` 用面试口吻的问题句，`gold_snippet` 取对应考点段落首句的**唯一片段**（≥12 字，且全文仅出现一次）：

```json
[
  {"id": "q001", "topic": "缓存穿透", "query": "什么是缓存穿透，有哪些解决方案？", "source_file": "redis.md", "gold_snippet": "缓存穿透指查询不存在的数据导致请求直接打到数据库"}
]
```

50 题覆盖 5 篇 × 10 考点，`id` 为 `q001`~`q050` 连续编号。

- [ ] **Step 3: 校验题库结构**

Run: `uv run python -c "import json;d=json.load(open('tests/acceptance/questions.json',encoding='utf-8'));assert len(d)==50;assert all(set(x)=={'id','topic','query','source_file','gold_snippet'} for x in d);assert len({x['id'] for x in d})==50;print('questions ok:',len(d))"`
Expected: `questions ok: 50`

- [ ] **Step 4: 校验 gold_snippet 唯一性（5 篇拼接后逐条检查）**

Run: `uv run python -c "import json,pathlib;t=''.join(pathlib.Path('tests/acceptance/corpus/'+x['source_file']).read_text(encoding='utf-8') for x in json.load(open('tests/acceptance/questions.json',encoding='utf-8')));import sys;bad=[x['id'] for x in json.load(open('tests/acceptance/questions.json',encoding='utf-8')) if t.count(x['gold_snippet'])!=1];assert not bad,bad;print('snippets unique')"`
Expected: `snippets unique`

- [ ] **Step 5: 快照基线**

Run: `New-Item -ItemType Directory -Force snapshots/task-1 | Out-Null; Copy-Item tests/acceptance snapshots/task-1 -Recurse`
（沙箱禁 git，快照用于任务 review 对比）

---

### Task 2: 验收脚本骨架 + P1-1 入库成功率

**Files:**
- Create: `_acceptance_p1.py`

- [ ] **Step 1: 写脚本骨架（报告收集器 + CLI + 服务组件初始化）**

```python
"""P1 验收（P1-1~P1-7）真实环境独立脚本：入库 → 召回 → 引用 → 降级 → 级联 → P95 → 切换。

用法：uv run python _acceptance_p1.py [--only p1-1|p1-2|...|p1-7|all] [--keep]
--keep 保留验收库（默认结束清理）。退出码 0 = 全部通过，1 = 有未通过项。
"""

import argparse
import json
import statistics
import sys
import time
import uuid
from pathlib import Path

from app.config import load_config
from app.retrieval.embedding import OpenAICompatEmbedding
from app.retrieval.es import ESManager
from app.retrieval.qdrant import QdrantManager
from app.retrieval.retrieve import RetrievalContext, retrieve
from app.store.knowledge import READY, KnowledgeStore

CORPUS_DIR = Path("tests/acceptance/corpus")
QUESTIONS = json.loads(Path("tests/acceptance/questions.json").read_text(encoding="utf-8"))


class Report:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, item: str, passed: bool, data: str = "") -> None:
        self.items.append({"item": item, "passed": passed, "data": data})
        mark = "PASS" if passed else "FAIL"
        print(f"[{mark}] {item}" + (f" | {data}" if data else ""))

    def summary(self) -> tuple[int, int]:
        ok = sum(1 for i in self.items if i["passed"])
        return ok, len(self.items) - ok


report = Report()
kb_id = f"kb-acceptance-{time.strftime('%Y%m%d%H%M%S')}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--only",
        default="all",
        choices=["p1-1", "p1-2", "p1-3", "p1-4", "p1-5", "p1-6", "p1-7", "all"],
    )
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    qdrant = QdrantManager(cfg)
    es = ESManager(cfg)
    embedding = OpenAICompatEmbedding(cfg)
    store = KnowledgeStore(cfg.retrieval.kb_db)
    ctx = RetrievalContext(cfg=cfg, qdrant=qdrant, es=es, embedding=embedding)

    checks = (
        ["p1-1", "p1-2", "p1-3", "p1-4", "p1-5", "p1-6", "p1-7"]
        if args.only == "all"
        else [args.only]
    )

    try:
        if "p1-1" in checks:
            p1_1(store, qdrant, es, embedding, cfg)
        if "p1-2" in checks:
            p1_2(ctx)
        if "p1-3" in checks:
            p1_3(ctx, cfg)
        if "p1-4" in checks:
            p1_4(ctx)
        if "p1-5" in checks:
            p1_5(store, qdrant, es, cfg)
        if "p1-6" in checks:
            p1_6()
        if "p1-7" in checks:
            p1_7(store, qdrant, es, cfg)
    finally:
        if not args.keep:
            cleanup(store, qdrant, es)

    ok, failed = report.summary()
    print(f"\n== P1 ACCEPTANCE SUMMARY == passed={ok} failed={failed}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 实现 P1-1（建库 → 入库 → 幂等重跑 → 状态统计）**

```python
def _ingest_file(store, qdrant, es, embedding, cfg, path: Path) -> tuple[bool, str]:
    from app.retrieval.ingest import file_id_of, ingest_document
    from app.store.knowledge import PROCESSING

    file_id = file_id_of(path)
    record = store.add_file(kb_id, file_id, path.name, str(path), path.stat().st_size)
    try:
        result = ingest_document(path, qdrant, es, embedding, cfg, kb_id=kb_id)
        store.update_file_status(record.id, READY, block_count=result.child_count)
        return True, f"parents={result.parent_count} children={result.child_count}"
    except Exception as e:  # noqa: BLE001 - 验收统计失败文件
        store.update_file_status(record.id, "failed", error=str(e)[:500])
        return False, repr(e)


def p1_1(store, qdrant, es, embedding, cfg) -> None:
    from app.retrieval.embedding import EmbeddingProvider  # 类型提示用

    store.create_kb(kb_id, "acceptance", embedding.model_id, embedding.dims)
    results = {}
    for p in sorted(CORPUS_DIR.glob("*.md")):
        ok, data = _ingest_file(store, qdrant, es, embedding, cfg, p)
        results[p.name] = (ok, data)
    ok_count = sum(1 for ok, _ in results.values() if ok)
    rate = ok_count / len(results)
    report.add(
        "P1-1 入库成功率",
        rate >= 0.95,
        f"{ok_count}/{len(results)} = {rate:.0%} | "
        + ", ".join(f"{n}:{'OK' if ok else 'FAIL'}" for n, (ok, _) in results.items()),
    )
    # 幂等重跑：同 file_id 先清旧再入库，块数应一致
    first = {n: c for n, (ok, d) in results.items() if ok for c in [d]}
    idem_ok = True
    for p in sorted(CORPUS_DIR.glob("*.md")):
        ok, data = _ingest_file(store, qdrant, es, embedding, cfg, p)
        idem_ok = idem_ok and ok and data == first[p.name]
    report.add("P1-1 幂等重跑（块数一致）", idem_ok)
```

- [ ] **Step 3: 运行 P1-1**

Run: `uv run python _acceptance_p1.py --only p1-1`
Expected: 两条 PASS（入库 5/5 = 100% ≥95%；幂等重跑块数一致），SUMMARY passed=2 failed=0

- [ ] **Step 4: 快照基线**

Run: `Copy-Item _acceptance_p1.py snapshots/task-2/`

---

### Task 3: P1-2 召回命中率 + P1-6 检索 P95（共用 50 题检索数据）

**Files:**
- Modify: `_acceptance_p1.py`

- [ ] **Step 1: 实现 gold 定位（ES match_phrase 定位标准出处父块）+ P1-2 检索**

```python
_GOLD: dict[str, str] = {}  # qid -> gold_parent_id
_TIMINGS: list[float] = []  # P1-6 采样


def _locate_gold(es, q: dict) -> str | None:
    client = es.get_client()
    resp = client.search(
        index=es.index,
        query={
            "bool": {
                "must": [
                    {"match_phrase": {"text": q["gold_snippet"]}},
                    {"term": {"kb_id": kb_id}},
                ]
            }
        },
        size=1,
        _source=["parent_id"],
    )
    hits = resp.get("hits", {}).get("hits", [])
    return hits[0]["_source"]["parent_id"] if hits else None


def p1_2(ctx) -> None:
    es = ctx.es
    locate_ok = 0
    for q in QUESTIONS:
        gid = _locate_gold(es, q)
        if gid:
            _GOLD[q["id"]] = gid
            locate_ok += 1
    report.add("P1-2 gold 定位率", locate_ok == len(QUESTIONS), f"{locate_ok}/{len(QUESTIONS)}")

    hit = miss = 0
    miss_list = []
    for q in QUESTIONS:
        gid = _GOLD.get(q["id"])
        if gid is None:
            continue
        t0 = time.perf_counter()
        r = retrieve(q["query"], kb_id, ctx.cfg, ctx.qdrant, ctx.es, ctx.embedding)
        _TIMINGS.append(r.total_ms)
        ok = any(c.parent_id == gid for c in r.citations)
        hit += ok
        if not ok:
            miss_list.append(f"{q['id']}({q['topic']})")
    rate = hit / len(QUESTIONS)
    report.add(
        "P1-2 Top-K=5 召回命中率",
        rate >= 0.80,
        f"{hit}/{len(QUESTIONS)} = {rate:.0%} | miss: {', '.join(miss_list) if miss_list else '-'}",
    )
```

- [ ] **Step 2: 实现 P1-6（复用 _TIMINGS 采样统计 P95）**

```python
def p1_6() -> None:
    if len(_TIMINGS) < len(QUESTIONS):
        report.add("P1-6 检索 P95", False, "无采样数据（需先跑 p1-2）")
        return
    times = sorted(_TIMINGS)
    p95 = times[int(len(times) * 0.95) - 1]
    report.add(
        "P1-6 单次检索 P95",
        p95 <= 2000,
        f"P95={p95:.0f}ms P50={statistics.median(times):.0f}ms max={max(times):.0f}ms",
    )
```

- [ ] **Step 3: 运行 P1-2 + P1-6**

Run: `uv run python _acceptance_p1.py --only p1-2 p1-6`（若 CLI 不支持多值，则分两次：`--only p1-2` 后 `--only p1-6`）
Expected: P1-2 gold 定位 50/50 PASS；命中率 ≥80%（若未达，输出 miss 清单并暂停 review 分析根因）；P1-6 P95 ≤2000ms PASS

---

### Task 4: P1-3 引用准确率（真实 LLM 出题 + LLM 判定）

**Files:**
- Modify: `_acceptance_p1.py`

- [ ] **Step 1: 实现真实出题 + 引用支撑性判定**

```python
def p1_3(ctx, cfg) -> None:
    from app.llm.client import DeepSeekClient
    from app.interview.nodes import ask_question_node
    from app.interview.state import initial_state
    from app.llm.keys import KeyStore

    llm = DeepSeekClient(cfg)
    key = KeyStore(cfg).get_global_key()
    judge_prompt = (
        "你是引用准确性验收裁判。判断下面的「引用片段」是否支撑「面试题目」，"
        "即引用内容与题目讨论同一知识点、能作为答题依据。\n"
        "题目：{question}\n引用：[{n}] {text}\n只输出 true 或 false。"
    )

    judged = total_cites = true_cites = 0
    details = []
    for q in QUESTIONS:
        gid = _GOLD.get(q["id"])
        if gid is None:
            continue
        state = initial_state(scene="fulltime", question_count=5, kb_id=kb_id)
        state["_api_key"] = key
        try:
            out = ask_question_node(state, llm, retrieval=ctx)
        except Exception as e:  # noqa: BLE001 - LLM 单题失败不中断
            details.append(f"{q['id']}:ask-error {repr(e)[:80]}")
            continue
        if out.get("_citations") is None or len(out["_citations"]) == 0:
            details.append(f"{q['id']}:no-citations")
            continue
        question = out["current_question"]
        for n, c in enumerate(out["_citations"], start=1):
            prompt = judge_prompt.format(question=question, n=n, text=c["text"][:200])
            try:
                raw, _ = llm.complete_sync(api_key=key, prompt=prompt)
                verdict = raw.strip().lower()
                is_true = verdict.startswith("true")
            except Exception as e:  # noqa: BLE001
                is_true = False
                details.append(f"{q['id']}:judge-error {repr(e)[:80]}")
            total_cites += 1
            true_cites += 1 if is_true else 0
        judged += 1

    rate = true_cites / total_cites if total_cites else 0.0
    report.add(
        "P1-3 引用准确率（normal 级）",
        rate >= 0.90 and judged >= 40,
        f"judged={judged}/50 cites={true_cites}/{total_cites} = {rate:.0%} | "
        + ("; ".join(details[:5]) if details else "-"),
    )
```

- [ ] **Step 2: 运行 P1-3（真实 LLM，50 题串行 + 每题引用逐条判定，预计耗时几分钟）**

Run: `uv run python _acceptance_p1.py --only p1-3`
Expected: 引用准确率 ≥90% 且判定题数 ≥40（单题 LLM 失败 ≤10 可接受）。若 <90%，输出细节清单供分析。

---

### Task 5: P1-4 四级降级路径 + P1-5 删除级联

**Files:**
- Modify: `_acceptance_p1.py`

- [ ] **Step 1: 实现 P1-4（真实双路 + 单路 stub 注入，确定性覆盖四级）**

```python
class _UnavailableQdrant:
    """检索不可用 stub：语义路降级（retrieve 捕获 RetrievalUnavailable 跳过）。"""

    def get_client(self):
        from app.retrieval import RetrievalUnavailable

        raise RetrievalUnavailable("disabled for acceptance")


class _UnavailableES:
    def get_client(self):
        from app.retrieval import RetrievalUnavailable

        raise RetrievalUnavailable("disabled for acceptance")


def p1_4(ctx) -> None:
    from app.retrieval.retrieve import FALLBACK, NORMAL, WEAK

    normal_q = QUESTIONS[0]["query"]  # 正常知识点：预期 normal/weak
    unrelated_q = "今天天气怎么样明天会下雨吗"  # 无关：预期 decline
    dual = retrieve(normal_q, kb_id, ctx.cfg, ctx.qdrant, ctx.es, ctx.embedding)
    es_only = retrieve(normal_q, kb_id, ctx.cfg, _UnavailableQdrant(), ctx.es, ctx.embedding)
    sem_only = retrieve(normal_q, kb_id, ctx.cfg, ctx.qdrant, _UnavailableES(), ctx.embedding)
    decline = retrieve(unrelated_q, kb_id, ctx.cfg, ctx.qdrant, ctx.es, ctx.embedding)

    checks = [
        (
            "双路命中 → normal/weak 且引用非空",
            dual.level in (NORMAL, WEAK) and bool(dual.citations),
            f"level={dual.level} cites={len(dual.citations)}",
        ),
        ("仅语义路 → fallback", sem_only.level == FALLBACK, f"level={sem_only.level}"),
        ("仅关键词路 → fallback", es_only.level == FALLBACK, f"level={es_only.level}"),
        (
            "无关查询 → decline 且引用空",
            decline.level == "decline" and not decline.citations,
            f"level={decline.level}",
        ),
    ]
    for name, passed, data in checks:
        report.add(f"P1-4 {name}", passed, data)
```

- [ ] **Step 2: 实现 P1-5（文件级删除 + 库级删除级联，Qdrant/ES 计数为 0）**

```python
def _qdrant_count(qdrant, qfilter) -> int:
    client = qdrant.get_client()
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    return client.count(
        collection_name=qdrant.collection,
        count_filter=Filter(
            must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in qfilter]
        ),
        exact=True,
    ).count


def _es_count(es, qfilter) -> int:
    client = es.get_client()
    must = [{"match": {k: v}} for k, v in qfilter]
    return client.count(index=es.index, query={"bool": {"must": must}})["count"]


def p1_5(store, qdrant, es, cfg) -> None:
    from app.retrieval.ingest import delete_document, file_id_of

    # 文件级：删第一篇
    first = sorted(CORPUS_DIR.glob("*.md"))[0]
    fid = file_id_of(first)
    delete_document(fid, qdrant, es)
    qc = _qdrant_count(qdrant, {"kb_id": kb_id, "file_id": fid})
    ec = _es_count(es, {"kb_id": kb_id, "file_id": fid})
    report.add(
        "P1-5 文件级删除级联（Qdrant+ES 0 命中）", qc == 0 and ec == 0, f"qdrant={qc} es={ec}"
    )

    # 库级：删除整个库（模拟 API 级联：delete_kb → delete_document 循环）
    files = store.delete_kb(kb_id)
    for f in files:
        delete_document(f.file_id, qdrant, es)
        (Path(f.path)).unlink(missing_ok=True)
    qc = _qdrant_count(qdrant, {"kb_id": kb_id})
    ec = _es_count(es, {"kb_id": kb_id})
    meta_left = store.get_kb(kb_id) is not None
    report.add(
        "P1-5 库级删除级联（三处 0 残留）",
        qc == 0 and ec == 0 and not meta_left and all(not (Path(f.path)).exists() for f in files),
        f"qdrant={qc} es={ec} meta_left={meta_left}",
    )
```

- [ ] **Step 3: 运行 P1-4 + P1-5**

Run: `uv run python _acceptance_p1.py --only p1-4 p1-5`
Expected: P1-4 四条 PASS；P1-5 两条 PASS（文件级 + 库级三处清零）

注意：P1-5 会删掉验收库全部数据，`--keep` 无效于此项（删除即验收本体）。P1-5 之后的项若需检索数据，须先重跑 P1-1。

---

### Task 6: P1-7 Embedding 切换重建 + 清理 + 报告落档

**Files:**
- Modify: `_acceptance_p1.py`
- Create: `docs/acceptance/p1-acceptance-report.md`（脚本生成，落档人工审阅）

- [ ] **Step 1: 实现 P1-7（切换 embedding → 全库重建 → 绑定一致 + 抽样检索正常）**

```python
def p1_7(store, qdrant, es, cfg) -> None:
    from app.retrieval.tasks import rebuild_all_background
    from app.retrieval.embedding import OpenAICompatEmbedding

    # 建一个独立验收库（P1-5 可能已清空主库，自给自足）
    kb2 = f"{kb_id}-switch"
    store.create_kb(kb2, "acceptance-switch", "bge-large-zh-v1.5", 1024)
    for p in sorted(CORPUS_DIR.glob("*.md")):
        ok, _ = _ingest_file(store, qdrant, es, embedding, cfg, p)  # noqa: F821 复用 p1_1 辅助
        if not ok:
            report.add("P1-7 切换前入库", False, p.name)
            return

    # 切换：构造新 embedding 实例（model_id 标记为切换后模型；TEI 忽略 model 字段，向量仍可用）
    switched = OpenAICompatEmbedding(cfg)
    switched._configured_model = "bge-large-zh-v1.5-switched"
    switched._dims = 1024
    res = rebuild_all_background(store, qdrant, es, switched, cfg)
    kbs = store.list_kbs()
    binding_ok = all(k.model_id == "bge-large-zh-v1.5-switched" and k.dims == 1024 for k in kbs)
    files_ok = all(f.status == READY for f in store.list_all_files())

    # 抽样 5 题验证检索正常（绑定已与当前模型一致）
    sample = QUESTIONS[:5]
    hit = 0
    for q in sample:
        gid = _locate_gold(es, q)
        if gid is None:
            continue
        r = retrieve(q["query"], kb2, cfg, qdrant, es, switched)
        hit += any(c.parent_id == gid for c in r.citations)
    report.add(
        "P1-7 切换重建 + 绑定一致",
        res["failed"] == 0 and binding_ok and files_ok and hit >= 4,
        f"rebuild ok={res['ok']} failed={res['failed']} binding_ok={binding_ok} files_ok={files_ok} sample_hit={hit}/5",
    )
    report.add(
        "P1-7 观察项：查询模型≠绑定模型拒绝校验未实现",
        False,
        "architecture v0.4 §4.3 约束在检索链路无实现；已记录，交用户裁决是否补实现",
    )
    # 清理切换库
    for f in store.delete_kb(kb2):
        from app.retrieval.ingest import delete_document

        delete_document(f.file_id, qdrant, es)
        (Path(f.path)).unlink(missing_ok=True)
```

- [ ] **Step 2: 实现 cleanup（结束时清理主验收库）**

```python
def cleanup(store, qdrant, es) -> None:
    from app.retrieval.ingest import delete_document

    files = store.delete_kb(kb_id)
    for f in files:
        try:
            delete_document(f.file_id, qdrant, es)
        except Exception as e:  # noqa: BLE001
            print(f"cleanup warn: {f.name} {repr(e)[:100]}")
        (Path(f.path)).unlink(missing_ok=True)
    print(f"cleanup: kb {kb_id} removed ({len(files)} files)")
```

- [ ] **Step 3: 全量运行（P1-1 → P1-7 串行，真实 LLM 部分耗时数分钟）**

Run: `uv run python _acceptance_p1.py`
Expected: SUMMARY passed=12 failed=0（P1-1×2、P1-2×2、P1-3×1、P1-4×4、P1-5×2、P1-6×1、P1-7×2 中 passed 计数随实现微调，failed 必须为 0；P1-7 观察项按「记录型 FAIL」处理或单独标注不参与 passed/failed，由实现者定，但需在报告中明确）

- [ ] **Step 4: 生成验收报告 `docs/acceptance/p1-acceptance-report.md`**

报告含：环境信息（服务版本探测结果）、七项验收数据表（标准/实测/结论）、未命中/未通过清单、观察项（查询拒绝校验缺口）、语料与题库说明。由实现者根据脚本输出撰写，人工审阅后随文档落档。

- [ ] **Step 5: 文档落档（CHANGELOG + project-status + PRD）**

- `CHANGELOG.md` 顶部新增「P1 验收完成」条目（格式沿用既有：日期/标题/描述/变更/验证/结构；验收结论与通过清单记入）
- `docs/project-status.md`：§4 追加 P1 验收行；§6.6 第 10 项 P1 验收标记 ✅ 并附实测数据；§8 决策日志追加
- `docs/prd.md`：§6 P1 验收标准行后标注验收结论（或 §8 追加验收记录，不动标准原文）
- 若验收中修复了任何缺陷，按既有流程先在 CHANGELOG 记录修复再记验收

- [ ] **Step 6: 回归确认（既有单测不受影响）**

Run: `uv run pytest -q`
Expected: 218 passed（验收脚本不在 tests/ 收集范围；若新增了 tests/ 下文件则相应增加）

---

## Self-Review 结果

- **Spec coverage**：P1-1~P1-7 每项一个验收实现 + 报告落档 + 文档同步；语料/题库/判定口径均来自 2026-09-17 需求澄清确认。环境前提与沙箱 git 限制已前置说明。
- **Placeholder scan**：无 TBD/TODO；每 Task 含完整代码或明确规范（语料考点清单）。Task 6 Step 1 中 `_ingest_file` 标注 `noqa: F821` 并在注释说明复用 p1_1 辅助——该函数定义于 Task 2，实现 Task 6 时将其提升为模块级函数以消除 F821（实现者注意）。
- **Type consistency**：`retrieve(query, kb_id, cfg, qdrant, es, embedding)`、`RetrievalContext(cfg,qdrant,es,embedding)`、`store.delete_kb(kb_id) -> list[KbFile]`、`rebuild_all_background(store,qdrant,es,embedding,cfg) -> dict[str,int]`、`OpenAICompatEmbedding(cfg)` 均与现有代码签名一致（已核对 retrieve.py/ingest.py/knowledge.py/tasks.py/api/knowledge.py）。`_configured_model`/`_dims` 为 embedding.py 内部属性（第 57 行附近），实现者以实际字段名为准。
