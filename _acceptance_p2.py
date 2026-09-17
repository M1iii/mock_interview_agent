"""P2 验收（P2-1~P2-5）真实环境独立脚本（Task 11 收尾）。

流程：P2-1 上传流（TestClient 内后台任务同步终态）→ P2-2 考点清单/配比/简历来源出题 →
P2-3 跨重启进程内模拟（SqliteSaver + SqliteSessionStore 同库重建）→ P2-4 web_verify
（占位 Key + BochaClient.search 类属性补丁）→ P2-5 端到端（简历关联会话 + 回答 + skip + finish）。

用法：uv run python _acceptance_p2.py [--only p2-1|p2-2|p2-3|p2-4|p2-5|all] [--keep]
--keep 保留验收数据（默认结束清理：删除本次上传的简历记录与文件、测试会话、
恢复 verify-key、删临时库）。
退出码 0 = 门禁项全部通过，1 = 门禁项有未通过项。不参与 pytest 收集。

报告项分三类（第 2 轮修复）：
- `kind="gate"` 门禁项：判定退出码，真实 FAIL 即应用/脚本缺陷；
- `kind="dep"` 依赖缺失 / 用法错误：如「无本次上传且库内无语料 stem 的 ready 简历」
  （需先跑 p2-1 / 单独 `--only p2-2|p2-5` 未上传语料）——只提示不判定，**不计入 failed**；
- `kind="obs"` 观察项：如失败简历 retry 路径，覆盖尚未纳入门禁的能力，**不计入成功率**，
  FAIL 只作提示（SUMMARY 单独列出）。
SUMMARY 分别打印三类计数，避免「依赖未满足」与「应用缺陷 FAIL」同形。
不修改任何 app/ 代码；暴露应用缺陷时记 FAIL + 归因落档。

最终审查修复轮（第 3 轮）要点：
- 修复 3-1：P2-4 保留 `BochaClient.search` 类属性补丁，但**新增门禁项「P2-4 Key 通路」**
  ——断言图实际使用的 `app.state.verify_ctx` 解析出的 Key 与搜索客户端 `_api_key`
  均等于占位 Key（并校验被调用的客户端实例持有的 Key）。修复前该客户端 `_api_key`
  恒为空（lifespan 一次性构造），本项必然 FAIL，即 BLOCKER「配置页 Key 传不到搜索客户端」
  的可复现证据；修复后为 PASS。P2-4 对照组（清 Key → verification=null）口径不变。

审查修复轮（第 2 轮）要点：
- minor-1：`_scoped_ready` 为空（依赖缺失/用法错误）改为 `kind="dep"` 记录，
  不计入 failed、不影响退出码，SUMMARY 单独列出。
- minor-2：P2-5 skip 循环命中 `error` 事件时先记录该 error 内容（门禁项）再 break，
  避免「题推进失败但报告断言仍 PASS」被掩盖（首次运行即暴露真实缺陷，见 CHANGELOG 顶部条目）。
- minor-3：p2_4/p2_5 内 5 处 `assert`（verify-key 置位/清空/get 校验）改为
  「记录 FAIL 项 + 提前 return」，且 main 对每个检查项兜底 try/except，
  保证全量运行总能输出 SUMMARY 与退出码。
- minor-4：`_check_report_summary` detail 追加原始 `summary`（截断）便于人工判读。
- 复审建议（非门禁）：新增 `kind="obs"` 观察项覆盖 `POST /api/resumes/{id}/retry`
  （R6「失败保留原文件可重试」）；本次无 failed 简历时先构造探针覆盖该路径，
  探针 id 只入 `_probe_ids`（cleanup 删除），不扰动 P2-1/P2-2/P2-5 取样口径。

审查修复轮（第 1 轮）要点：
- F3：P2-5 自设占位 verify-key + 补丁 `BochaClient.search`，使第 1 题真实走通 VerifyContext
  全链路（不依赖检索服务），断言 assess 事件 verification 非空；报告摘要补强必备键与四维校验；
  结束后 finally 还原补丁与 verify-key。
- F4：P2-4 未配置 Key 对照组复用与第 1 步完全相同的 answer，并旁证
  `GET /api/settings/verify-key` → is_set=False（排除「LLM 判为非事实性」的混淆解释）。
- F6：本次运行上传的 resume_id 显式记录，P2-1 统计 / P2-2 抽样 / P2-5 建会话只使用这些 id，
  不再按全表 created_at DESC 取头部；清理只针对本次上传的记录与文件。
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
from app.store.resume import FAILED, READY, ResumeStore

CORPUS_DIR = Path("tests/acceptance/resumes")
GOLD = json.loads(Path("tests/acceptance/resume_gold.json").read_text(encoding="utf-8"))

# 标准（PRD §6 P2）
STD_READY_RATE = 0.90  # 20 份解析成功率 ≥90%（ready ≥18/20）
STD_FIELD_HIT = 0.85  # ready 简历 profile_json 关键字段命中率 ≥85%
STD_POINT_COUNT = 10  # ready 简历考点清单 ≥10 项
STD_KEYWORD_HIT = 0.80  # 简历来源题干含 gold 考点关键词 ≥80%
RATIO_PLAN = {0.3: [1, 4, 7], 0.8: [1, 2, 3, 4, 6, 7, 8, 9], 0.5: [1, 3, 5, 7, 9]}

# P2-5 占位搜索 Key（仅验收用；结束还原为空）
P2_VERIFY_KEY = "bocha-acceptance"
# 报告摘要必备键 + 四维键（报告 prompt 用「沟通表达」，evaluate 用「表达清晰度」，均算齐全）
SUMMARY_KEYS = ("total_score", "dimensions", "strengths", "weaknesses", "review")
DIM_ALIASES = {
    "技术深度": ("技术深度",),
    "沟通表达": ("沟通表达", "表达清晰度"),
    "问题解决": ("问题解决", "解决问题"),
    "项目经验": ("项目经验",),
}
VALID_STATUS = ("verified", "uncertain", "unconfirmed")

# P2-3 临时库（gitignored data/），cleanup 时移除
P23_DB = PROJECT_ROOT / "data" / "_acceptance_p2_3.db"

_uploaded_ids: list[str] = []  # 本次运行上传的简历 id（F6：唯一可信取样范围 + cleanup）
_uploaded_by_name: dict[str, str] = {}  # 本次运行：语料文件名 → resume_id
_probe_ids: list[str] = []  # 观察项构造的 failed 探针简历 id（仅 cleanup，不参与 P2-1/P2-2 取样）
_session_ids: list[str] = []  # P2-4/P2-5 创建的会话 id（cleanup）
_p23_instances: list = []  # P2-3 实例（cleanup 关连接）


class Report:
    """三类报告项（第 2 轮修复）：

    - `gate`（默认）：门禁项，决定退出码；FAIL = 应用缺陷或脚本缺陷；
    - `dep`：依赖缺失 / 用法错误（如未先跑 p2-1 上传语料）——**不计入 failed**，仅提示；
    - `obs`：观察项（如 retry 路径）——**不计入成功率门禁**，FAIL 仅提示。

    仅 `gate` 类参与 `gate_failed` 计数，`dep` / `obs` 在 SUMMARY 中单独列出，
    避免「依赖未满足」「观察项未过」与「应用缺陷 FAIL」同形。
    """

    KINDS = ("gate", "dep", "obs")
    MARKS = {"gate": ("PASS", "FAIL"), "obs": ("PASS", "FAIL"), "dep": ("PASS", "SKIP")}

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, item: str, passed: bool, data: str = "", kind: str = "gate") -> None:
        assert kind in self.KINDS, f"unknown kind: {kind}"
        self.items.append({"item": item, "passed": passed, "data": data, "kind": kind})
        mark = self.MARKS[kind][0 if passed else 1]
        print(f"[{mark}][{kind}] {item}" + (f" | {data}" if data else ""))

    def summary(self) -> dict[str, int]:
        def _count(kind: str, passed: bool | None = None) -> int:
            return sum(
                1
                for i in self.items
                if i["kind"] == kind and (passed is None or i["passed"] is passed)
            )

        return {
            "gate_passed": _count("gate", True),
            "gate_failed": _count("gate", False),
            "obs_total": _count("obs"),
            "obs_failed": _count("obs", False),
            "dep_total": _count("dep"),
        }


report = Report()


def _add_dep(item: str, reason: str) -> None:
    """记录「依赖缺失 / 用法错误」项（minor-1）：不计入 failed、不影响退出码。

    触发场景：`--only p2-2` / `--only p2-5` 未先跑 p2-1 上传语料，或语料上传全失败，
    此时 `_scoped_ready` 返回空 —— 属调用方用法问题，不是应用缺陷。
    """
    report.add(item, False, f"usage-error｜{reason}", kind="dep")


def _ready_resumes(store: ResumeStore) -> list:
    return [r for r in store.list_resumes() if r.status == READY]


def _run_uploads(store: ResumeStore, status: str | None = None) -> list:
    """本次运行上传的简历（F6：不按全表 created_at DESC 取头部）。

    status 非空时按状态过滤。P2-1 统计 / P2-2 抽样 / P2-5 建会话一律以本列表为准，
    避免抽入用户既有简历或 `--keep` 残留。
    """
    recs = [store.get_resume(rid) for rid in dict.fromkeys(_uploaded_ids)]
    recs = [r for r in recs if r is not None]
    return [r for r in recs if status is None or r.status == status]


def _scoped_ready(store: ResumeStore) -> tuple[list, str]:
    """可用的 ready 简历 + 取样口径（F6）。

    优先本次运行上传的 ready 简历（scope="run"）；为空（如单独 `--only p2-2/p2-5`
    未跑 P2-1）时回退到「语料 stem 作用域」——仅取文件名 stem 命中 gold 的简历，
    仍排除用户既有简历；`--keep` 残留亦属语料 stem，日志如实标注 scope="corpus"。
    """
    run_ready = _run_uploads(store, READY)
    if run_ready:
        return run_ready, "run"
    corpus_ready = [r for r in _ready_resumes(store) if Path(r.file_name).stem in GOLD]
    if corpus_ready:
        print(f"[info] 本次运行无上传记录，回退语料 stem 作用域取样（n={len(corpus_ready)}）")
    return corpus_ready, "corpus"


def _kb_id_if_available(cfg) -> str | None:
    """首个含 ready 文件的知识库 id；检索服务未监听时返回 None（P2-5 省略 kb，静默降级）。"""
    ctx = getattr(app.state, "retrieval", None)
    if ctx is not None:
        try:
            if not (ctx.qdrant.is_available() and ctx.es.is_available()):
                print("[info] 检索服务未监听 → P2-5 省略 kb 参数（静默降级）")
                return None
        except Exception as e:  # noqa: BLE001 - 探测异常同样降级
            print(f"[info] 检索服务探测异常 → P2-5 省略 kb 参数：{repr(e)[:100]}")
            return None

    from app.store.knowledge import READY as KB_READY
    from app.store.knowledge import KnowledgeStore

    ks = KnowledgeStore(PROJECT_ROOT / cfg.retrieval.kb_db)
    for k in ks.list_kbs():
        if any(getattr(f, "status", "") == KB_READY for f in (k.files or [])):
            return k.id
    return None


def _check_report_summary(summary) -> tuple[bool, str]:
    """报告结构化摘要校验：必备键存在 + total_score 0–100 + 四维键齐全（含别名容错）。

    detail 追加原始 `summary`（minor-4：截断至 400 字符，保留断言口径不变），
    便于人工判读模型实际返回的字段名/取值。
    """
    if not isinstance(summary, dict):
        return False, f"summary={type(summary).__name__}"
    missing = [k for k in SUMMARY_KEYS if summary.get(k) is None]
    ts = summary.get("total_score")
    ts_ok = isinstance(ts, (int, float)) and not isinstance(ts, bool) and 0 <= ts <= 100
    dims = summary.get("dimensions")
    dim_hits: dict[str, str | None] = {}
    if isinstance(dims, dict):
        dim_hits = {
            std: next((a for a in aliases if a in dims), None)
            for std, aliases in DIM_ALIASES.items()
        }
    dim_missing = [std for std, hit in dim_hits.items() if hit is None] or (
        [] if isinstance(dims, dict) else list(DIM_ALIASES)
    )
    ok = not missing and ts_ok and not dim_missing
    dim_text = json.dumps(dims, ensure_ascii=False) if isinstance(dims, dict) else dims
    raw = json.dumps(summary, ensure_ascii=False, default=str)
    if len(raw) > 400:
        raw = f"{raw[:400]}…(truncated, total {len(raw)} chars)"
    return ok, (
        f"missing={missing or '-'} total_score={ts}({type(ts).__name__}) "
        f"dims={dim_text} dim_missing={dim_missing or '-'} | raw_summary={raw}"
    )


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


def _session_status(client: TestClient, session_id: str) -> str:
    """会话当前状态（ongoing/finished）；查不到返回 unknown。"""
    r = client.get("/api/sessions")
    if r.status_code != 200:
        return "unknown"
    for s in r.json():
        if s.get("id") == session_id:
            return s.get("status", "unknown")
    return "unknown"


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
            _uploaded_by_name[p.name] = rid  # F6：本次运行的文件名 → id 映射（唯一样本来源）
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
    # F6：results 的键是文件名（str），按本次运行的 _uploaded_by_name 映射取 id（勿当 Path 用）
    hit = 0
    miss_detail: list[str] = []
    for fname, (ok, _) in sorted(results.items()):
        if not ok:
            continue
        gold = GOLD.get(Path(fname).stem)
        rid = _uploaded_by_name.get(fname)
        rec = store.get_resume(rid) if rid else None
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
        rid = _uploaded_by_name.get(fname)
        rec = store.get_resume(rid) if rid else None
        if rec is None:
            mism.append(f"{fname}:record-missing")
            continue
        n = len(store.list_points(rec.id))
        if rec.point_count != n or n < STD_POINT_COUNT:
            mism.append(f"{fname}:count={rec.point_count} rows={n}")
    report.add(
        "P2-1 考点清单落表一致（point_count=rows≥10）",
        not mism,
        f"mismatch: {', '.join(mism) if mism else '-'}",
    )

    # 观察项（非门禁）：失败简历 retry 路径（R6），覆盖 POST /api/resumes/{id}/retry
    failed: list[tuple[str, str]] = []
    for fname in sorted(results):
        rid = _uploaded_by_name.get(fname)
        rec = store.get_resume(rid) if rid else None
        if rec is not None and rec.status == FAILED:
            failed.append((fname, rec.id))
    _retry_observation(client, store, failed, cfg)


def _make_failed_probe(store: ResumeStore, cfg) -> tuple[str, str] | None:
    """构造 failed 简历探针（复制语料文件 + 入库后置 failed），供 retry 路径观察项使用。

    仅当本次运行无 failed 简历时构造（复审建议允许「先构造」）。探针 id 记入 `_probe_ids`：
    cleanup 会删记录 + 物理文件，但**不进入** `_uploaded_ids`，故不扰动 P2-1/P2-2/P2-5 取样口径。
    """
    srcs = sorted(CORPUS_DIR.glob("*.md"))
    if not srcs:
        return None
    src = srcs[0]
    rid = f"r-{uuid.uuid4().hex[:8]}"
    dest_dir = PROJECT_ROOT / cfg.resume.upload_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{rid}_{src.name}"
    dest.write_bytes(src.read_bytes())
    store.add_resume(rid, src.name, str(dest.relative_to(PROJECT_ROOT)), dest.stat().st_size)
    store.update_failed(rid, "acceptance-probe：构造 failed 样本以覆盖 retry 路径")
    _probe_ids.append(rid)
    return src.name, rid


def _retry_observation(
    client: TestClient, store: ResumeStore, failed: list[tuple[str, str]], cfg
) -> None:
    """观察项（`kind="obs"`，不计入成功率门禁）：失败简历重试路径。

    覆盖 `POST /api/resumes/{id}/retry`——该端点此前 pytest 与验收脚本均无覆盖，
    对应 P2 需求 R6「失败保留原文件可重试」。判定：HTTP 200 且返回体状态为
    processing/ready（TestClient 下响应体在后台任务执行前生成，故应为
    `update_processing` 后的 processing），同时旁证原文件仍在磁盘（R6 前提）。
    最终状态与耗时一并记录（重试若仍失败则落 failed，属如实记录，不影响门禁）。
    本次运行无 failed 简历 → 构造探针覆盖该路径；构造失败才如实记录「未触发」。
    """
    item = "观察项｜P2-1 失败简历 retry 路径（R6：失败保留原文件可重试）"
    source = "本次运行 failed 简历"
    if not failed:
        probe = _make_failed_probe(store, cfg)
        if probe is None:
            report.add(
                item,
                True,
                "本次运行无 status=failed 简历且探针构造失败（无语料可复制）→ 该路径未触发",
                kind="obs",
            )
            return
        failed = [probe]
        source = "构造探针（本次运行无 failed 简历）"

    fname, rid = failed[0]
    before = store.get_resume(rid)
    try:  # R6 前提：失败保留原文件（相对项目根）
        file_kept = bool(before and (PROJECT_ROOT / before.path).exists())
    except Exception as e:  # noqa: BLE001 - 观察项不阻断门禁
        file_kept = f"探测异常 {repr(e)[:60]}"
    try:
        t0 = time.time()
        r = client.post(f"/api/resumes/{rid}/retry")
        elapsed = time.time() - t0
        resp_status = (r.json().get("resume") or {}).get("status")
        after = store.get_resume(rid)
        ok = r.status_code == 200 and resp_status in ("processing", "ready")
        report.add(
            item,
            ok,
            f"样本={source} file={fname} rid={rid} 原文件保留={file_kept} http={r.status_code} "
            f"resp_status={resp_status} final_status={after.status if after else 'None'} "
            f"耗时={elapsed:.1f}s" + (f" resp={r.text[:150]}" if r.status_code != 200 else ""),
            kind="obs",
        )
    except Exception as e:  # noqa: BLE001 - 观察项不阻断门禁
        report.add(
            item, False, f"retry 调用异常（观察项，不影响门禁）：{repr(e)[:200]}", kind="obs"
        )


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
    ready, scope = _scoped_ready(store)

    # 1) 考点清单 ≥10（minor-1：无 ready 简历属依赖缺失 → dep，不计入 failed）
    if not ready:
        _add_dep(
            "P2-2 考点清单 ≥10 项",
            "无可用 ready 简历（依赖 p2-1 上传语料；非应用缺陷）",
        )
    else:
        below = [
            f"{r.file_name}:{r.point_count}"
            for r in ready
            if (r.point_count or 0) < STD_POINT_COUNT
        ]
        report.add(
            "P2-2 考点清单 ≥10 项",
            not below,
            f"ready={len(ready)} scope={scope} below: {', '.join(below) if below else '-'}",
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
    # 口径说明（F1）：本项只验证 ResumeStore → prompt 的「注入链路一致性」（fake LLM
    # 原样回显考点清单块），不是真实「题目与清单相关性」证据；真实相关性待真实 LLM 抽样判定。
    from app.interview.nodes import ask_question_node
    from app.interview.state import initial_state

    samples = ready[:3]  # F6：ready 仅含本次运行上传（或语料 stem 作用域），不带入用户数据
    if not samples:
        # minor-1：依赖缺失（未先跑 p2-1 上传语料 / 语料全解析失败）→ 用法错误，不计入 failed
        _add_dep(
            "P2-2 简历来源题干含考点关键词（注入链路一致性，≥80%）",
            "无可用 ready 简历可抽样（需先跑 p2-1 上传语料；非应用缺陷）",
        )
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
        f"口径=注入链路一致性 scope={scope}；"
        f"关键词覆盖={total_hit}/{total_gold} = {hit_rate:.0%}；"
        f"题干命中={q_with_hit}/{len(samples)} = {q_rate:.0%} | {'; '.join(per_resume)}"
    )
    report.add(
        "P2-2 简历来源题干含考点关键词（注入链路一致性，≥80%）",
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
# P2-4 web_verify：占位 Key + BochaClient.search 类属性补丁 + Key 通路断言
# ---------------------------------------------------------------------------


def p2_4(client: TestClient, cfg) -> None:
    from app.verify import bocha as bocha_mod
    from app.verify.bocha import SearchResult

    sid = _create_session(client, scene="fulltime", question_count=5, skip_opening=True)
    evts = _chat(client, sid, {})
    if not any(ev == "error" for ev, _ in evts):
        _ = _sse_text(evts)  # 题干（占位消费）

    original_search = bocha_mod.BochaClient.search
    used_clients: list = []  # 被实际调用的搜索客户端实例（Key 通路证据）

    def _fake_search(self, query: str, count: int = 3):
        used_clients.append(self)
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

    # F4：对照组复用同一条 answer（仅 Key 状态不同），排除「LLM 判为非事实性」的混淆解释
    answer = (
        "Redis 支持 RDB 和 AOF 两种持久化方式，AOF 通过追加写日志记录每一条写命令，"
        "重启后可通过日志恢复数据。"
    )

    try:
        # 1) 配占位 Key → 打补丁 → 事实性回答 → assess 事件 verification 非空
        # minor-3：原 assert 改为「记录 FAIL + return」（不抛 AssertionError 中断脚本）
        r = client.put("/api/settings/verify-key", json={"verify_key": P2_VERIFY_KEY})
        if r.status_code != 200:
            report.add(
                "P2-4 事实核验（配置 Key + 补丁）",
                False,
                f"set verify-key http {r.status_code}: {r.text[:200]}",
            )
            return
        bocha_mod.BochaClient.search = _fake_search

        evts = _chat(client, sid, {"answer": answer})
        assesses = [d for ev, d in evts if ev == "assess"]
        errors = [d for ev, d in evts if ev == "error"]
        v = assesses[-1].get("verification") if assesses else None
        ok = (
            not errors
            and v is not None
            and v.get("status") in VALID_STATUS
            and bool(v.get("sources"))
            and bool(v.get("claims"))
        )
        v_text = json.dumps(v, ensure_ascii=False) if v else "null"
        report.add(
            "P2-4 事实核验（配置 Key + 补丁）",
            ok,
            f"answer_len={len(answer)} verification={v_text}",
        )

        # 1b) Key 通路门禁项（修复轮新增）：证明「配置页设置的 Key 真正到达搜索客户端」。
        # 修复前 lifespan 一次性构造 BochaClient（此时 KeyStore 无 Key）→ 客户端 _api_key 恒为空
        # → search() 恒抛 BochaError → 本项必然 FAIL（KeyStore 里即使有 Key 也无效）。
        # 断言对象 = 图实际使用的 VerifyContext（app.state.verify_ctx，lifespan 注入的同一实例）。
        resolved = getattr(app.state, "verify_ctx", None)
        ctx_key = resolved.resolve_key() if resolved is not None else ""
        client_key = getattr(resolved._search_client(), "_api_key", "") if resolved else ""
        used_keys = [getattr(c, "_api_key", "") for c in used_clients]
        key_ok = (
            resolved is not None
            and ctx_key == P2_VERIFY_KEY
            and client_key == P2_VERIFY_KEY
            and (not used_keys or all(k == P2_VERIFY_KEY for k in used_keys))
        )
        report.add(
            "P2-4 Key 通路（配置页 Key 到达搜索客户端）",
            key_ok,
            f"graph_verify_ctx_key={ctx_key!r} resolved_client_key={client_key!r} "
            f"search_calls={len(used_clients)} called_client_keys={used_keys}",
        )

        # 2) 对照组：清 Key → 旁证 GET is_set=False → 提交**同一条 answer** → verification 为 null
        item2 = "P2-4 未配置 Key 跳过核验（同一 answer 对照）"
        r = client.put("/api/settings/verify-key", json={"verify_key": ""})
        if r.status_code != 200:
            report.add(item2, False, f"clear verify-key http {r.status_code}: {r.text[:200]}")
            return
        key_state = client.get("/api/settings/verify-key").json()
        if key_state.get("is_set") is not False:
            report.add(item2, False, f"verify-key 未清空：{key_state}")
            return

        evts2 = _chat(client, sid, {"answer": answer})
        assesses2 = [d for ev, d in evts2 if ev == "assess"]
        v2 = assesses2[-1].get("verification") if assesses2 else "no-assess"
        report.add(
            item2,
            v2 is None and key_state.get("is_set") is False,
            f"is_set={key_state.get('is_set')} answer_len={len(answer)} "
            f"verification={v2 if isinstance(v2, str) else 'null'}",
        )
    finally:
        bocha_mod.BochaClient.search = original_search


# ---------------------------------------------------------------------------
# P2-5 端到端：简历关联会话 → 答 1 题 → skip → finish → 报告
# ---------------------------------------------------------------------------


def p2_5(client: TestClient, cfg) -> None:
    from app.verify import bocha as bocha_mod
    from app.verify.bocha import SearchResult

    store = ResumeStore(PROJECT_ROOT / cfg.resume.db)
    ready, scope = _scoped_ready(store)  # F6：本次运行上传的 ready 简历优先
    if not ready:
        # minor-1：依赖缺失（无本次上传且库内无语料 stem 的 ready 简历）→ 用法错误，
        # 不计入 failed、不影响退出码；SUMMARY 中与「真实 FAIL」分列。
        _add_dep(
            "P2-5 端到端链路",
            "无可用 ready 简历（本次无上传且库内无语料 stem 的 ready 简历；需先跑 p2-1 上传语料）",
        )
        return
    rec = ready[0]
    print(f"[info] P2-5 取样简历={rec.file_name} scope={scope}")

    # kb 可选：检索服务未监听或无可用户 → 省略（静默降级，不依赖检索即可真实触发核验）
    kb_id = _kb_id_if_available(cfg)

    payload = {
        "scene": "fulltime",
        "question_count": 5,
        "resume_id": rec.id,
        "interview_type": "technical",
    }
    if kb_id:
        payload["kb_id"] = kb_id
    sid = _create_session(client, **payload)

    original_search = bocha_mod.BochaClient.search

    def _fake_search(self, query: str, count: int = 3) -> list:
        """P2-5 核验链路补丁：固定返回与断言句一致的 Redis 持久化信源。"""
        return [
            SearchResult(
                title="Redis 持久化机制详解",
                url="https://example.com/redis-persistence",
                snippet="Redis 提供 RDB（定时快照）与 AOF（追加写命令日志）两种持久化方式，"
                "重启后可通过 RDB 文件或重放 AOF 日志恢复数据。",
            ),
            SearchResult(
                title="Redis RDB 与 AOF 对比",
                url="https://example.com/rdb-vs-aof",
                snippet="RDB 是周期性快照，AOF 记录每一条写命令，两者可同时开启以兼顾恢复与安全。",
            ),
        ]

    # F3：事实性回答（含可联网核验的技术事实），走通 LLM 判定 → 搜索 → 二次判定全链路
    fact_answer = (
        "Redis 的持久化有 RDB 和 AOF 两种方式：RDB 是定时快照，把内存数据写入二进制文件；"
        "AOF 是追加写日志，记录每一条写命令，Redis 重启后通过重放日志恢复数据。"
        "我在订单系统里用 Redis 缓存热点数据，同时开启 AOF 保证重启后缓存可重建。"
    )

    item_v = "P2-5 第 1 题核验触发（VerifyContext 全链路）"
    try:
        # F3-1：自设占位 verify-key + 补丁搜索 → 第 1 题真实触发核验（VerifyContext 全链路）
        # minor-3：原 assert 改为「记录 FAIL + return」（不抛 AssertionError 中断脚本）
        r = client.put("/api/settings/verify-key", json={"verify_key": P2_VERIFY_KEY})
        if r.status_code != 200:
            report.add(item_v, False, f"set verify-key http {r.status_code}: {r.text[:200]}")
            return
        key_state = client.get("/api/settings/verify-key").json()
        if key_state.get("is_set") is not True:
            report.add(item_v, False, f"verify-key 未生效：{key_state}")
            return
        bocha_mod.BochaClient.search = _fake_search

        # 第 1 题（技术面首题即简历来源题）→ 事实性回答
        evts = _chat(client, sid, {})
        errs = [d for ev, d in evts if ev == "error"]
        if errs:
            report.add(
                "P2-5 端到端链路",
                False,
                f"首题出题 error：{json.dumps(errs[-1], ensure_ascii=False)[:300]}",
            )
            return
        evts = _chat(client, sid, {"answer": fact_answer})
        assesses = [d for ev, d in evts if ev == "assess"]
        errors = [d for ev, d in evts if ev == "error"]
        if not assesses:
            report.add(item_v, False, "答题后无 assess 事件")
            return
        v = assesses[-1].get("verification")
        v_ok = (
            not errors
            and isinstance(v, dict)
            and v.get("status") in VALID_STATUS
            and bool(v.get("sources"))
            and bool(v.get("claims"))
        )
        v_text = json.dumps(v, ensure_ascii=False) if v else "null"
        report.add(
            item_v,
            v_ok,
            f"kb={kb_id or 'None'} verification={v_text}"
            + (f" errors={json.dumps(errors[-1], ensure_ascii=False)[:200]}" if errors else ""),
        )

        # 其余题 skip（自适应：最后一题 skip 会自动出报告并置 finished）
        # minor-2：命中 error 事件时先记录该 error 内容（门禁项）再 break，
        # 避免「题推进失败但报告断言仍 PASS」被掩盖。
        skip_err: str | None = None
        for _ in range(10):
            if _session_status(client, sid) == "finished":
                break
            evts = _chat(client, sid, {"action": "skip"})
            skip_errors = [d for ev, d in evts if ev == "error"]
            if skip_errors:
                skip_err = json.dumps(skip_errors[-1], ensure_ascii=False)[:300]
                break
        report.add(
            "P2-5 skip 推进（无 error 事件）",
            skip_err is None,
            (
                f"skip 返回 error（题目推进失败，后续报告断言不可信）：{skip_err}"
                if skip_err
                else "skip 全程无 error 事件"
            ),
        )

        # 收口：未结束 → 显式 finish；已结束（末题 skip 自动出报告）→ 直接取报告
        if _session_status(client, sid) == "finished":
            rr = client.get(f"/api/sessions/{sid}/report")
            finish_path = f"GET /report http={rr.status_code}"
        else:
            rr = client.post(f"/api/sessions/{sid}/finish")
            finish_path = f"POST /finish http={rr.status_code}"
        if rr.status_code != 200:
            report.add("P2-5 端到端链路", False, f"报告获取失败（{finish_path}）：{rr.text[:200]}")
            return
        body = rr.json()
        report_text = body.get("report", "")
        summary = body.get("summary")
        summary_ok, summary_detail = _check_report_summary(summary)
        ok = ("面试报告" in report_text) and isinstance(summary, dict) and summary_ok
        summary_kind = "dict" if isinstance(summary, dict) else str(summary)
        report.add(
            "P2-5 端到端链路（报告正文 + 结构化摘要 _report_summary）",
            ok,
            f"kb={kb_id or 'None'} {finish_path} report_chars={len(report_text)} "
            f"summary={summary_kind} {summary_detail}",
        )

        # 导出路径：GET /report 可用
        r2 = client.get(f"/api/sessions/{sid}/report")
        export_ok = r2.status_code == 200 and bool(r2.json().get("report"))
        report.add("P2-5 报告导出（GET /report）", export_ok, f"export_http={r2.status_code}")
    finally:
        # F3-3：补丁与 verify-key 一律还原/清理（含异常/早退路径）
        bocha_mod.BochaClient.search = original_search
        try:
            client.put("/api/settings/verify-key", json={"verify_key": ""})
        except Exception as e:  # noqa: BLE001 - 还原失败仅告警
            print(f"p2-5 restore warn: verify-key {repr(e)[:100]}")


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------


def _purge_upload_files(cfg) -> None:
    """兜底清理：仅删本次运行上传的物理文件（删除接口失败/记录已删时残留）。"""
    base = PROJECT_ROOT / cfg.resume.upload_dir
    if not base.is_dir():
        return
    for rid in dict.fromkeys([*_uploaded_ids, *_probe_ids]):
        for f in base.glob(f"{rid}_*"):
            try:
                f.unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001 - Windows 占用容忍
                print(f"cleanup warn: unlink {f.name} {repr(e)[:100]}")


def cleanup(client: TestClient, cfg) -> None:
    for sid in _session_ids:
        try:
            client.delete(f"/api/sessions/{sid}")
        except Exception as e:  # noqa: BLE001 - 清理失败仅告警
            print(f"cleanup warn: session {sid} {repr(e)[:100]}")
    for rid in [*_uploaded_ids, *_probe_ids]:  # 探针记录同样清理（不留残留）
        try:
            client.delete(f"/api/resumes/{rid}")
        except Exception as e:  # noqa: BLE001 - 清理失败仅告警
            print(f"cleanup warn: resume {rid} {repr(e)[:100]}")
    _purge_upload_files(cfg)  # F6：只动本次上传的记录与文件，不触碰用户既有数据
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
        steps = {
            "p2-1": lambda: p2_1(client, cfg),
            "p2-2": lambda: p2_2(client, cfg),
            "p2-3": lambda: p2_3(cfg),
            "p2-4": lambda: p2_4(client, cfg),
            "p2-5": lambda: p2_5(client, cfg),
        }
        try:
            for name in checks:
                try:
                    steps[name]()
                except Exception as e:  # noqa: BLE001 - minor-3：单检查项异常不中断全量运行
                    report.add(
                        f"{name} 执行异常（该检查项中断，后续项仍继续）", False, repr(e)[:300]
                    )
        finally:
            if not args.keep:
                cleanup(client, cfg)

    s = report.summary()
    print("\n== P2 ACCEPTANCE SUMMARY ==")
    print(f"门禁项 gate：passed={s['gate_passed']} failed={s['gate_failed']}（决定退出码）")
    print(
        f"观察项 observe：total={s['obs_total']} failed={s['obs_failed']}"
        "（不计入 P2-1 成功率与退出码，仅提示）"
    )
    print(f"依赖缺失/用法错误 dep：total={s['dep_total']}（usage-error，不计入 failed）")
    for i in report.items:
        if i["kind"] == "dep":
            print(f"  [dep] {i['item']} | {i['data']}")
    if s["gate_failed"]:
        print("真实 FAIL 明细（门禁项）：")
        for i in report.items:
            if i["kind"] == "gate" and not i["passed"]:
                print(f"  [gate-FAIL] {i['item']} | {i['data']}")
    sys.exit(0 if s["gate_failed"] == 0 else 1)


if __name__ == "__main__":
    main()
