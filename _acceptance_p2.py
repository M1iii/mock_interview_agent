"""P2 验收（P2-1~P2-5）真实环境独立脚本（Task 11 收尾）。

流程：P2-1 上传流（TestClient 内后台任务同步终态）→ P2-2 考点清单/配比/简历来源出题 →
P2-3 跨重启进程内模拟（SqliteSaver + SqliteSessionStore 同库重建）→ P2-4 web_verify
（占位 Key + BochaClient.search 类属性补丁）→ P2-5 端到端（简历关联会话 + 回答 + skip + finish）。

用法：uv run python _acceptance_p2.py [--only p2-1|p2-2|p2-3|p2-4|p2-5|all] [--keep]
--keep 保留验收数据（默认结束清理：删除简历记录/文件、测试会话、恢复 verify-key、删临时库）。
退出码 0 = 全部通过，1 = 有未通过项。不参与 pytest 收集。
不修改任何 app/ 代码；暴露应用缺陷时记 FAIL + 归因落档。
"""

import argparse
import gc
import json
import sys
import time
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from omegaconf import OmegaConf

from app.config import PROJECT_ROOT, load_config
from app.interview.ratio import resume_question_indices
from app.main import app
from app.store.resume import ResumeStore

CORPUS_DIR = Path("tests/acceptance/resumes")
GOLD = json.loads(Path("tests/acceptance/resume_gold.json").read_text(encoding="utf-8"))

# 标准（PRD §6 P2）
STD_READY_RATE = 0.90  # 20 份解析成功率 ≥90%（ready ≥18/20）
STD_FIELD_HIT = 0.85  # ready 简历 profile_json 关键字段命中率 ≥85%
STD_POINT_COUNT = 10  # ready 简历考点清单 ≥10 项
STD_KEYWORD_HIT = 0.80  # 简历来源题干含 gold 考点关键词 ≥80%
RATIO_PLAN = {0.3: [1, 4, 7], 0.8: [1, 2, 3, 4, 6, 7, 8, 9], 0.5: [1, 3, 5, 7, 9]}

# P2-3 临时库（gitignored data/），cleanup 时移除
P23_DB = PROJECT_ROOT / "data" / "_acceptance_p2_3.db"

_uploaded_ids: list[str] = []  # P2-1 上传的简历 id（cleanup）
_session_ids: list[str] = []  # P2-4/P2-5 创建的会话 id（cleanup）
_p23_instances: list = []  # P2-3 实例（cleanup 关连接）


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


def _ready_resumes(store: ResumeStore) -> list:
    from app.store.resume import READY

    return [r for r in store.list_resumes() if r.status == READY]


def _chat(client: TestClient, session_id: str, payload: dict) -> list[tuple[str, dict]]:
    """POST /api/chat/{id}，解析 SSE 事件序列 [(event, data), ...]。"""
    r = client.post(f"/api/chat/{session_id}", json=payload)
    assert r.status_code == 200, f"chat http {r.status_code}: {r.text[:300]}"
    events: list[tuple[str, dict]] = []
    for block in r.text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        lines = block.split("\n")
        ev = lines[0].removeprefix("event:").strip()
        data_lines = [
            ln.removeprefix("data:").strip() for ln in lines[1:] if ln.startswith("data:")
        ]
        payload_obj = json.loads("\n".join(data_lines)) if data_lines else {}
        events.append((ev, payload_obj))
    return events


def _create_session(client: TestClient, **overrides) -> str:
    payload = {
        "scene": "fulltime",
        "question_count": 5,
        "skip_opening": True,
        "interview_type": "technical",
    }
    payload.update(overrides)
    r = client.post("/api/sessions", json=payload)
    assert r.status_code == 200, f"create session http {r.status_code}: {r.text[:300]}"
    sid = r.json()["id"]
    _session_ids.append(sid)
    return sid


def _sse_text(events: list[tuple[str, dict]]) -> str:
    return "".join(d.get("content", "") for ev, d in events if ev == "token")


# ---------------------------------------------------------------------------
# P2-1 上传流：解析成功率 + 字段命中
# ---------------------------------------------------------------------------


def p2_1(client: TestClient, cfg) -> None:
    store = ResumeStore(PROJECT_ROOT / cfg.resume.db)
    results: dict[str, tuple[bool, str]] = {}
    for p in sorted(CORPUS_DIR.glob("*")):
        rid = None
        try:
            with p.open("rb") as fh:
                r = client.post(
                    "/api/resumes",
                    files={"file": (p.name, fh, "application/octet-stream")},
                )
            assert r.status_code == 200, f"upload http {r.status_code}: {r.text[:200]}"
            rid = r.json()["resume"]["id"]
            _uploaded_ids.append(rid)
            # 后台任务在 TestClient 内同步执行完毕，状态已终态；轮询保留兼容
            deadline = time.time() + 120
            while time.time() < deadline:
                rec = store.get_resume(rid)
                if rec is None or rec.status != "processing":
                    break
                time.sleep(1)
            rec = store.get_resume(rid)
            if rec is None:
                results[p.name] = (False, "record missing")
            elif rec.status == "ready":
                results[p.name] = (True, f"points={rec.point_count}")
            else:
                results[p.name] = (False, f"status={rec.status} err={rec.error}")
        except Exception as e:  # noqa: BLE001 - 单份失败不中断
            results[p.name] = (False, repr(e)[:200])

    ok_count = sum(1 for ok, _ in results.values() if ok)
    rate = ok_count / len(results)
    report.add(
        "P2-1 解析成功率",
        rate >= STD_READY_RATE,
        f"ready={ok_count}/{len(results)} = {rate:.0%} | "
        + ", ".join(f"{n}:{'OK' if ok else 'FAIL'}" for n, (ok, _) in results.items()),
    )

    # 字段命中：name 子串 + skills 关键词 ≥1 出现在 profile_json
    # 注意：results 的键是文件名（str），此处按文件名取 gold 与 DB 记录（勿当 Path 用）
    hit = 0
    miss_detail: list[str] = []
    for fname, (ok, _) in sorted(results.items()):
        if not ok:
            continue
        gold = GOLD.get(Path(fname).stem)
        rec = store.get_resume(_rid_of(store, fname))
        if rec is None or gold is None or not rec.profile_json:
            miss_detail.append(f"{fname}:no-profile")
            continue
        name_hit = gold["basic"]["name"] in rec.profile_json
        skill_hit = any(s in rec.profile_json for s in gold["skills"])
        if name_hit and skill_hit:
            hit += 1
        else:
            miss_detail.append(f"{fname}:name={name_hit} skill={skill_hit}")
    hit_rate = hit / ok_count if ok_count else 0.0
    miss_text = ", ".join(miss_detail) if miss_detail else "-"
    report.add(
        "P2-1 字段命中率（name+skills）",
        hit_rate >= STD_FIELD_HIT,
        f"{hit}/{ok_count} = {hit_rate:.0%} | miss: {miss_text}",
    )

    # 考点清单直读一致：resumes.point_count == len(list_points) 且 ≥10
    mism: list[str] = []
    for fname, (ok, _) in sorted(results.items()):
        if not ok:
            continue
        rec = store.get_resume(_rid_of(store, fname))
        n = len(store.list_points(rec.id))
        if rec.point_count != n or n < STD_POINT_COUNT:
            mism.append(f"{fname}:count={rec.point_count} rows={n}")
    report.add(
        "P2-1 考点清单落表一致（point_count=rows≥10）",
        not mism,
        f"mismatch: {', '.join(mism) if mism else '-'}",
    )


def _rid_of(store: ResumeStore, file_name: str) -> str:
    for r in store.list_resumes():
        if r.file_name == file_name:
            return r.id
    raise KeyError(file_name)


# ---------------------------------------------------------------------------
# P2-2 考点清单 + 配比 + 简历来源出题（fake LLM）
# ---------------------------------------------------------------------------


class _FakeLLM:
    """占位出题 LLM：回显 prompt 的【简历考点清单】区块作为题干（含 title/detail/原文）。

    真实 RESUME_QUESTION 模板中考点块标记为「【简历考点清单】（含原文片段，供出题回溯）」，
    块尾为「出题要求：」行（无方括号），据此截取；截取失败回退占位串。
    """

    def __init__(self) -> None:
        self.last_prompt = ""

    def complete_sync(self, api_key: str, prompt: str, callbacks: list | None = None):
        self.last_prompt = prompt
        start = prompt.find("【简历考点清单】")
        end = prompt.find("出题要求：")
        block = prompt[start:end].strip() if start != -1 and end != -1 else "占位题干"
        return block, {}


def p2_2(client: TestClient, cfg) -> None:
    store = ResumeStore(PROJECT_ROOT / cfg.resume.db)
    ready = _ready_resumes(store)

    # 1) 考点清单 ≥10
    below = [
        f"{r.file_name}:{r.point_count}" for r in ready if (r.point_count or 0) < STD_POINT_COUNT
    ]
    report.add(
        "P2-2 考点清单 ≥10 项",
        bool(ready) and not below,
        f"ready={len(ready)} below: {', '.join(below) if below else '-'}",
    )

    # 2) 配比纯函数复算（P2 设计 §5：tech 3 道 / beha 8 道 / comp 5 道，按 10 题计）
    cfg_ratios = {
        "technical": float(cfg.resume.ratio.technical),
        "behavioral": float(cfg.resume.ratio.behavioral),
        "comprehensive": float(cfg.resume.ratio.comprehensive),
    }
    ratio_data = [f"cfg={cfg_ratios}"]
    ratio_ok = cfg_ratios == {"technical": 0.3, "behavioral": 0.8, "comprehensive": 0.5}
    for r, expect in RATIO_PLAN.items():
        got = resume_question_indices(10, r)
        ratio_ok = ratio_ok and got == expect
        ratio_data.append(f"r={r}->{got}")
    report.add("P2-2 配比纯函数复算", ratio_ok, " | ".join(ratio_data))

    # 3) 简历来源出题（fake LLM 回显考点块）：题干含 gold 考点关键词 ≥80%
    from app.interview.nodes import ask_question_node
    from app.interview.state import initial_state

    samples = ready[:3]
    if not samples:
        report.add("P2-2 简历来源题干含考点关键词（≥80%）", False, "无 ready 简历可抽样")
        return
    api_key = cfg.llm.api_key
    fake = _FakeLLM()
    total_hit = total_gold = 0
    q_with_hit = 0
    per_resume: list[str] = []
    for rec in samples:
        stem = Path(rec.file_name).stem
        gold_points = GOLD.get(stem, {}).get("points", [])
        total_gold += len(gold_points)
        state = initial_state(
            scene="fulltime", question_count=10, resume_id=rec.id, interview_type="technical"
        )
        state["_api_key"] = api_key
        # question_index=0 → 1-based 1，技术面配比 [1,4,7] 首题即简历题（ratio 0.3）
        try:
            out = ask_question_node(state, fake, resume_store=store, cfg=cfg)
        except Exception as e:  # noqa: BLE001
            per_resume.append(f"{stem}:ask-error {repr(e)[:80]}")
            continue
        question = out.get("current_question", "")
        hits = [k for k in gold_points if k in question]
        total_hit += len(hits)
        q_with_hit += 1 if hits else 0
        per_resume.append(f"{stem}:{len(hits)}/{len(gold_points)}")
    hit_rate = total_hit / total_gold if total_gold else 0.0
    q_rate = q_with_hit / len(samples)
    detail = (
        f"关键词覆盖={total_hit}/{total_gold} = {hit_rate:.0%}；"
        f"题干命中={q_with_hit}/{len(samples)} = {q_rate:.0%} | {'; '.join(per_resume)}"
    )
    report.add(
        "P2-2 简历来源题干含考点关键词（≥80%）",
        hit_rate >= STD_KEYWORD_HIT and q_rate >= STD_KEYWORD_HIT,
        detail,
    )


# ---------------------------------------------------------------------------
# P2-3 跨重启（进程内模拟）：SqliteSaver + SqliteSessionStore 同库重建
# ---------------------------------------------------------------------------


def _noop_node(state):
    return {}


def _compile_noop(ckpt):
    from app.interview.state import InterviewState

    g = StateGraph(InterviewState)
    g.add_node("noop", _noop_node)
    g.add_edge(START, "noop")
    g.add_edge("noop", END)
    return g.compile(checkpointer=ckpt)


def p2_3(cfg) -> None:
    from app.store.checkpointer import create_checkpointer
    from app.store.sessions import SqliteSessionStore

    P23_DB.unlink(missing_ok=True)
    sid = f"p2-3-{uuid.uuid4().hex[:8]}"

    # 第一代：写会话元数据 + checkpoint 状态
    store1 = SqliteSessionStore(P23_DB)
    _p23_instances.append(store1)
    store1.create(sid, "fulltime", 10, False, None, "r-restore-sample", "technical")
    ckpt1 = create_checkpointer(OmegaConf.create({"interview": {"db": str(P23_DB)}}))
    _p23_instances.append(ckpt1)
    c1 = _compile_noop(ckpt1)
    c1.invoke(
        {
            "messages": [HumanMessage(content="P2-3 持久化验证消息")],
            "scene": "fulltime",
            "question_count": 10,
            "question_index": 3,
            "current_question": "测试题",
            "status": "ongoing",
            "resume_id": "r-restore-sample",
            "interview_type": "technical",
        },
        {"configurable": {"thread_id": sid}},
    )

    # 模拟关闭/置空
    try:
        store1._conn.close()
    except Exception as e:  # noqa: BLE001 - 已关闭容忍
        print(f"p2-3 close warn: {repr(e)[:100]}")
    try:
        ckpt1.conn.close()
    except Exception as e:  # noqa: BLE001 - 已关闭容忍
        print(f"p2-3 close warn: {repr(e)[:100]}")
    for inst in (store1, ckpt1):
        if inst in _p23_instances:
            _p23_instances.remove(inst)
    gc.collect()

    # 第二代：同 db 重建
    store2 = SqliteSessionStore(P23_DB)
    _p23_instances.append(store2)
    meta = store2.get(sid)
    meta_ok = meta is not None and meta["id"] == sid and meta["status"] == "ongoing"
    meta_ok = meta_ok and meta["resume_id"] == "r-restore-sample"

    ckpt2 = create_checkpointer(OmegaConf.create({"interview": {"db": str(P23_DB)}}))
    _p23_instances.append(ckpt2)
    c2 = _compile_noop(ckpt2)
    snap = c2.get_state({"configurable": {"thread_id": sid}})
    vals = snap.values or {}
    msgs = vals.get("messages", [])
    hist_ok = (
        len(msgs) == 1
        and msgs[0].content == "P2-3 持久化验证消息"
        and vals.get("question_index") == 3
        and vals.get("status") == "ongoing"
        and vals.get("resume_id") == "r-restore-sample"
    )
    report.add(
        "P2-3 会话记录恢复（同库重建）",
        meta_ok,
        f"sid={sid} status={meta['status'] if meta else 'None'}",
    )
    report.add(
        "P2-3 对话历史恢复（checkpointer）",
        hist_ok,
        f"msgs={len(msgs)} qidx={vals.get('question_index')} resume={vals.get('resume_id')}",
    )


# ---------------------------------------------------------------------------
# P2-4 web_verify：占位 Key + BochaClient.search 类属性补丁
# ---------------------------------------------------------------------------


def p2_4(client: TestClient, cfg) -> None:
    from app.verify import bocha as bocha_mod
    from app.verify.bocha import SearchResult

    sid = _create_session(client, scene="fulltime", question_count=5, skip_opening=True)
    evts = _chat(client, sid, {})
    if not any(ev == "error" for ev, _ in evts):
        _ = _sse_text(evts)  # 题干（占位消费）

    original_search = bocha_mod.BochaClient.search

    def _fake_search(self, query: str, count: int = 3):
        return [
            SearchResult(
                title="Redis 持久化机制详解",
                url="https://example.com/redis-persistence",
                snippet="Redis 支持 RDB 和 AOF 两种持久化方式，AOF 以追加日志方式记录每一条写命令，"
                "重启后通过日志恢复数据。",
            ),
            SearchResult(
                title="Redis RDB 与 AOF 对比",
                url="https://example.com/rdb-vs-aof",
                snippet="RDB 是周期性快照持久化，AOF 记录每一条写命令，AOF 数据安全性更高。",
            ),
        ]

    try:
        # 1) 配占位 Key → 打补丁 → 事实性回答 → assess 事件 verification 非空
        r = client.put("/api/settings/verify-key", json={"verify_key": "bocha-acceptance"})
        assert r.status_code == 200, f"set verify-key http {r.status_code}: {r.text[:200]}"
        bocha_mod.BochaClient.search = _fake_search

        answer = (
            "Redis 支持 RDB 和 AOF 两种持久化方式，AOF 通过追加写日志记录每一条写命令，"
            "重启后可通过日志恢复数据。"
        )
        evts = _chat(client, sid, {"answer": answer})
        assesses = [d for ev, d in evts if ev == "assess"]
        errors = [d for ev, d in evts if ev == "error"]
        v = assesses[-1].get("verification") if assesses else None
        ok = (
            not errors
            and v is not None
            and v.get("status") in ("verified", "uncertain", "unconfirmed")
            and bool(v.get("sources"))
            and bool(v.get("claims"))
        )
        report.add(
            "P2-4 事实核验（配置 Key + 补丁）",
            ok,
            f"verification={json.dumps(v, ensure_ascii=False) if v else 'null'}",
        )

        # 2) 清 Key（保持未配置态）→ 提交 → verification 为 null（跳过路径）
        r = client.put("/api/settings/verify-key", json={"verify_key": ""})
        assert r.status_code == 200, f"clear verify-key http {r.status_code}"
        evts2 = _chat(
            client,
            sid,
            {"answer": "继续回答：Redis 过期策略含惰性删除与定期删除，淘汰策略支持 LRU 与 LFU。"},
        )
        assesses2 = [d for ev, d in evts2 if ev == "assess"]
        v2 = assesses2[-1].get("verification") if assesses2 else "no-assess"
        report.add(
            "P2-4 未配置 Key 跳过核验",
            v2 is None,
            f"verification={v2 if isinstance(v2, str) else 'null'}",
        )
    finally:
        bocha_mod.BochaClient.search = original_search


# ---------------------------------------------------------------------------
# P2-5 端到端：简历关联会话 → 答 1 题 → skip → finish → 报告
# ---------------------------------------------------------------------------


def p2_5(client: TestClient, cfg) -> None:
    store = ResumeStore(PROJECT_ROOT / cfg.resume.db)
    ready = _ready_resumes(store)
    if not ready:
        report.add("P2-5 端到端链路", False, "无 ready 简历（需先 p2-1 或历史数据）")
        return
    rec = ready[0]

    # kb 可选：首个含 ready 文件的库，无则省略
    from app.store.knowledge import READY, KnowledgeStore

    ks = KnowledgeStore(PROJECT_ROOT / cfg.retrieval.kb_db)
    kb_id = None
    for k in ks.list_kbs():
        if any(getattr(f, "status", "") == READY for f in (k.files or [])):
            kb_id = k.id
            break

    payload = {
        "scene": "fulltime",
        "question_count": 5,
        "resume_id": rec.id,
        "interview_type": "technical",
    }
    if kb_id:
        payload["kb_id"] = kb_id
    sid = _create_session(client, **payload)

    # 第 1 题（技术面首题为简历来源题）→ 事实性回答
    evts = _chat(client, sid, {})
    if any(ev == "error" for ev, _ in evts):
        report.add("P2-5 端到端链路", False, "首题出题 error")
        return
    fact_answer = (
        "我之前负责订单系统的重构，使用 Redis 缓存热点数据，通过多级缓存解决缓存雪崩问题。"
    )
    evts = _chat(client, sid, {"answer": fact_answer})
    assesses = [d for ev, d in evts if ev == "assess"]
    if not assesses:
        report.add("P2-5 端到端链路", False, "答题后无 assess 事件")
        return

    # 其余题 skip
    for _ in range(3):
        evts = _chat(client, sid, {"action": "skip"})
        if any(ev == "error" for ev, d in evts):
            break

    # finish → 报告 + 结构化摘要
    r = client.post(f"/api/sessions/{sid}/finish")
    if r.status_code != 200:
        report.add("P2-5 端到端链路", False, f"finish http {r.status_code}: {r.text[:200]}")
        return
    body = r.json()
    report_text = body.get("report", "")
    summary = body.get("summary")
    ok = ("面试报告" in report_text) and isinstance(summary, dict)
    summary_kind = "dict" if isinstance(summary, dict) else str(summary)
    report.add(
        "P2-5 端到端链路（报告+摘要）",
        ok,
        f"kb={kb_id or 'None'} report_chars={len(report_text)} summary={summary_kind}",
    )

    # 导出路径：GET /report 可用
    r2 = client.get(f"/api/sessions/{sid}/report")
    export_ok = r2.status_code == 200 and bool(r2.json().get("report"))
    report.add("P2-5 报告导出（GET /report）", export_ok, f"http={r2.status_code}")


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------


def cleanup(client: TestClient) -> None:
    for sid in _session_ids:
        try:
            client.delete(f"/api/sessions/{sid}")
        except Exception as e:  # noqa: BLE001 - 清理失败仅告警
            print(f"cleanup warn: session {sid} {repr(e)[:100]}")
    for rid in _uploaded_ids:
        try:
            client.delete(f"/api/resumes/{rid}")
        except Exception as e:  # noqa: BLE001 - 清理失败仅告警
            print(f"cleanup warn: resume {rid} {repr(e)[:100]}")
    try:
        client.put("/api/settings/verify-key", json={"verify_key": ""})
    except Exception as e:  # noqa: BLE001
        print(f"cleanup warn: verify-key {repr(e)[:100]}")
    for inst in _p23_instances:
        conn = getattr(inst, "conn", None) or getattr(inst, "_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception as e:  # noqa: BLE001 - 已关闭/占用容忍
                print(f"cleanup warn: close {repr(e)[:100]}")
    try:
        P23_DB.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 - Windows 文件占用容忍
        print(f"cleanup warn: p2-3 db {repr(e)[:100]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--only",
        default="all",
        nargs="+",
        choices=["p2-1", "p2-2", "p2-3", "p2-4", "p2-5", "all"],
    )
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    checks = ["p2-1", "p2-2", "p2-3", "p2-4", "p2-5"] if "all" in args.only else args.only
    cfg = load_config()

    with TestClient(app) as client:
        try:
            if "p2-1" in checks:
                p2_1(client, cfg)
            if "p2-2" in checks:
                p2_2(client, cfg)
            if "p2-3" in checks:
                p2_3(cfg)
            if "p2-4" in checks:
                p2_4(client, cfg)
            if "p2-5" in checks:
                p2_5(client, cfg)
        finally:
            if not args.keep:
                cleanup(client)

    ok, failed = report.summary()
    print(f"\n== P2 ACCEPTANCE SUMMARY == passed={ok} failed={failed}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
