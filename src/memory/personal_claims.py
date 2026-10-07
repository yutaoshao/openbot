"""Parse and render traceable personal-memory claims.

Personal dossiers historically stored the answer and its provenance on one
Markdown bullet.  The parser keeps that format as the source of truth while
allowing prompt builders to render the answer and provenance as separate layers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EVIDENCE_KEYS = (
    "事件时间",
    "陈述时间",
    "状态",
    "来源",
    "依据",
    "事实键",
    "事件ID",
    "事件名称",
    "阶段",
    "待跟进",
    "追问",
    "偏好范围",
    "偏好键",
    "适用场景",
)
_EVIDENCE_SEPARATOR = re.compile(r"；(?=(?:" + "|".join(map(re.escape, _EVIDENCE_KEYS)) + r")：)")


@dataclass(frozen=True)
class PersonalClaim:
    """One Markdown claim with its answer and verification metadata separated."""

    fact: str
    evidence: tuple[tuple[str, str], ...] = ()

    @property
    def evidence_map(self) -> dict[str, str]:
        return dict(self.evidence)

    @property
    def evidence_text(self) -> str:
        return "；".join(f"{key}：{value}" for key, value in self.evidence if value)


def parse_claim_line(line: str) -> PersonalClaim | None:
    """Parse a dossier bullet; return ``None`` for headings or free-form text."""
    if not line.startswith("- "):
        return None
    body = line[2:].strip()
    parts = _EVIDENCE_SEPARATOR.split(body)
    fact = parts[0].strip()
    if not fact:
        return None
    evidence: list[tuple[str, str]] = []
    for part in parts[1:]:
        if "：" not in part:
            continue
        key, value = part.split("：", 1)
        if key in _EVIDENCE_KEYS and value.strip():
            evidence.append((key, value.strip()))
    return PersonalClaim(fact=fact, evidence=tuple(evidence))


def parse_claims(content: str) -> list[PersonalClaim]:
    """Return all parseable claims from a Markdown document."""
    return [claim for line in content.splitlines() if (claim := parse_claim_line(line)) is not None]


def searchable_claim_text(content: str, *, include_evidence: bool = False) -> str:
    """Build lexical/vector text without forcing provenance into normal prompts."""
    claim = parse_claim_line(content.strip())
    if claim is None:
        return content
    if include_evidence and claim.evidence_text:
        return f"{claim.fact}\n{claim.evidence_text}"
    return claim.fact


def searchable_document_text(content: str, *, include_evidence: bool = False) -> str:
    """Build retrieval text from every line while omitting provenance by default."""
    return "\n".join(
        searchable_claim_text(line, include_evidence=include_evidence)
        for line in content.splitlines()
    )


def render_claim_line(line: str, *, include_evidence: bool) -> str:
    """Render one claim as answer text, optionally followed by verification data."""
    claim = parse_claim_line(line)
    if claim is None:
        return line
    rendered = f"- {claim.fact}"
    if include_evidence and claim.evidence_text:
        rendered += f"\n  核验信息：{claim.evidence_text}"
    return rendered


def render_claim_section(content: str, *, include_evidence: bool) -> str:
    """Render a retrieved paragraph while preserving its topic/section labels."""
    lines = content.splitlines()
    rendered: list[str] = []
    for line in lines:
        if line.startswith("- "):
            rendered.append(render_claim_line(line, include_evidence=include_evidence))
        else:
            rendered.append(line)
    return "\n".join(rendered)
