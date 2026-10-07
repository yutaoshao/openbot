from src.memory.personal_claims import (
    parse_claim_line,
    render_claim_line,
    searchable_document_text,
)


def test_claim_parser_separates_fact_from_existing_inline_metadata() -> None:
    line = (
        "- 滔的父亲给他1800元。；事件时间：未注明；陈述时间：2026-10-06；"
        "状态：unknown；来源：message:source；事实键：living_expense_source"
    )

    claim = parse_claim_line(line)

    assert claim is not None
    assert claim.fact == "滔的父亲给他1800元。"
    assert claim.evidence_map["来源"] == "message:source"
    assert "来源：message:source" not in render_claim_line(line, include_evidence=False)
    assert "来源：message:source" in render_claim_line(line, include_evidence=True)


def test_searchable_document_text_omits_evidence_by_default() -> None:
    content = "## 已确认事实\n- 生活费来源：父亲给 1800 元；来源：message:1；依据：用户纠正"

    assert "生活费来源" in searchable_document_text(content)
    assert "message:1" not in searchable_document_text(content)
    assert "message:1" in searchable_document_text(content, include_evidence=True)
