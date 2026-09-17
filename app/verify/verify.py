"""事实性陈述联网核验：LLM 判定 → 博查搜索 → LLM 二次判定。

结论三态：verified（已核验）/ uncertain（存疑）/ unconfirmed（无法确认）。
降级与边界（P2 设计 §6）：未配置 Key / 请求失败 / 超时 → 静默跳过（不阻断评估）。
核验结果并入 SSE assess 事件 payload（不新增事件类型）。
"""

import json
import re
from dataclasses import dataclass, field

from loguru import logger

from app.llm.client import DeepSeekClient
from app.verify.bocha import DEFAULT_BASE_URL, BochaClient, BochaError

JUDGE_PROMPT = """\
你是事实性陈述判定助手。判断以下候选人回答是否包含可联网核验的事实性陈述（如公司、日期、
技术特性、公开数据等）。主观感受、观点、个人经历不算事实性陈述。

【回答】
{answer}

只输出一个 JSON 对象：
{{"is_factual": true/false, "claims": ["事实性陈述1", "事实性陈述2"]}}

要求：
- claims 仅列事实性陈述（≤3 条），每条是独立的、可检索的短句
- 没有事实性陈述时 is_factual=false，claims 为空数组
"""

VERIFY_PROMPT = """\
你是事实核验助手。基于搜索结果判断以下事实性陈述是否成立。

【陈述】
{claims}

【搜索结果】
{search_block}

只输出一个 JSON 对象：
{{"status": "verified|uncertain|unconfirmed", "reason": "判定理由（结合信源说明）"}}

判定规则：
- 搜索结果显示有信源支持陈述 → verified
- 搜索结果显示存在矛盾或证据不足 → uncertain
- 搜索失败或完全没有相关信源 → unconfirmed
"""


@dataclass
class Verification:
    status: str  # verified / uncertain / unconfirmed
    reason: str
    claims: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)  # [{title, url, snippet}]
    skipped: bool = False  # 跳过核验（Key 缺失等）

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "claims": self.claims,
            "sources": self.sources,
            "skipped": self.skipped,
        }


class VerifyContext:
    """评估节点核验注入组件（图构建时注入，测试可替换为 fake）。"""

    def __init__(self, llm: DeepSeekClient, cfg, key_store, bocha=None) -> None:
        self._llm = llm
        self._cfg = cfg
        self._key_store = key_store
        self._bocha = bocha or BochaClient(
            key_store.get_verify_key() or "",
            base_url=cfg.verify.get("base_url", DEFAULT_BASE_URL),
            timeout=float(cfg.verify.get("timeout", 10.0)),
        )

    def verify(self, api_key: str, answer: str) -> Verification | None:
        """核验一条回答；返回 None 表示跳过（无 Key / 非事实性）。

        异常（搜索失败/LLM 失败）一律降级：返回 unconfirmed 或 None，不向评估抛错。
        """
        verify_key = self._key_store.get_verify_key()
        if not verify_key:
            return None  # 未配置搜索 Key → 静默跳过（设计 §6 降级）
        if not answer or not answer.strip():
            return None

        try:
            judge_raw, _ = self._llm.complete_sync(
                api_key=api_key, prompt=JUDGE_PROMPT.format(answer=answer[:2000])
            )
            judge = _parse_json(judge_raw)
        except Exception as e:  # noqa: BLE001 - 判定失败视为无事实性陈述
            logger.warning("verify judge failed: {err}", err=repr(e))
            return None

        if not judge.get("is_factual"):
            return None
        claims = [str(c).strip() for c in (judge.get("claims") or []) if str(c).strip()][:3]
        if not claims:
            return None

        sources: list[dict] = []
        for claim in claims:
            try:
                for r in self._bocha.search(claim, count=int(self._cfg.verify.top_k)):
                    if r.url:
                        sources.append({"title": r.title, "url": r.url, "snippet": r.snippet})
            except BochaError as e:
                logger.warning("verify search failed: {err}", err=repr(e))
        if not sources:
            return Verification(status="unconfirmed", reason="搜索无可用信源", claims=claims)

        search_block = "\n".join(
            f"[{i + 1}] {s['title']}（{s['url']}）：{s['snippet']}" for i, s in enumerate(sources)
        )
        try:
            verdict_raw, _ = self._llm.complete_sync(
                api_key=api_key,
                prompt=VERIFY_PROMPT.format(
                    claims="\n".join(f"- {c}" for c in claims), search_block=search_block
                ),
            )
            verdict = _parse_json(verdict_raw)
            status = verdict.get("status")
            if status not in ("verified", "uncertain", "unconfirmed"):
                status = "unconfirmed"
            reason = str(verdict.get("reason", "")).strip() or "无法确认"
        except Exception as e:  # noqa: BLE001 - 二次判定失败降级
            logger.warning("verify verdict failed: {err}", err=repr(e))
            status, reason = "unconfirmed", "核验判定失败"
        return Verification(status=status, reason=reason, claims=claims, sources=sources)


def _parse_json(raw: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
    payload = m.group(1) if m else raw
    data = json.loads(payload)
    return data if isinstance(data, dict) else {}
