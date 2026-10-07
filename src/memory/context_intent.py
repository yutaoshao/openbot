"""Small deterministic intent gates for memory context expansion."""

from __future__ import annotations

_EVIDENCE_TERMS = (
    "依据",
    "证据",
    "来源",
    "原话",
    "核验",
    "核实",
    "怎么知道",
    "凭什么",
    "哪条记录",
    "什么时候说",
    "是真的吗",
    "确定吗",
    "历史",
    "过去",
    "之前",
    "记录",
)
_OUTCOME_TERMS = (
    "后来",
    "之后",
    "结果",
    "进展",
    "完成了吗",
    "做完了吗",
    "有没有发生",
    "实际",
    "是否完成",
    "有没有做",
    "打了吗",
    "接种了吗",
    "计划",
    "待跟进",
)


def requires_evidence_context(query: str) -> bool:
    """Expand provenance and original speech only for verification-style queries."""
    normalized = query.strip().lower()
    return any(term in normalized for term in (*_EVIDENCE_TERMS, *_OUTCOME_TERMS))
