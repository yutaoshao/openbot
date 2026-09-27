"""Extract attributable personal claims, with adjacent speech only as context."""

from __future__ import annotations

import json
from typing import Any

from src.memory.structured_json import parse_json_array_response

EXTRACTION_PROMPT = """你整理用户个人档案。输入包含当前用户原话、相邻对话及既有事件目录。
只提取当前用户这次明确表达的新事实、纠正、偏好和重要事件阶段。
相邻助手话语只用于解释“就这么办”等指代，助手建议不能自动当成用户决定。
旧档案只用于关联主体/事件，不得复制成此次新事实。普通咨询不是计划。
返回 JSON 数组，无新信息返回 []。每项字段：
topic: 个人/宠物/健康/关系/项目；subject: 主体名；aliases: 别名数组；
kind: confirmed/event/inference/uncertain；fact: 中文完整陈述，稳定属性用“键：值”；
event_time: 用户明确说出的事件时间，缺失为空（可用陈述日期解析“今天”，不能猜日期）；
status: discussed/planned/ongoing/done/cancelled/unknown；
correction: 只有用户明确纠正同一属性才为 true；basis: 推测的原话依据。
体重等测量值是 event。出生日期保留用户给出的精度，禁止由年龄倒推精确生日。
偏好使用 kind=confirmed，同时填 preference_key、scope（通用/场景）、triggers（场景关键词）。
通用仅用于明确的语言、回答方式等跨主题偏好；主题内习惯用场景，不把一次请求升级为偏好。
重要经历（咨询、决定、实施、取消、结果）填 event_name、stage
（origin/discussion/decision/rationale/action/outcome）。已有事件填目录提供的 event_id；
新事件 event_id 留空，用稳定且可区分具体事件的 event_name。
同一事件之后取消/完成要复用原事件，不另建事件。
只有用户明确计划/正在经历且确实未知的后续，可填 followup_field 和 followup_question
（自然中文问句，包含主体和具体事件，以问号结尾）。普通咨询不得填追问。
推测与不确定内容不得更改已确认事实。
"""


async def extract_claims(gateway: Any, payload: dict) -> list[dict]:
    response = await gateway.chat(
        [
            {"role": "system", "content": EXTRACTION_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
        ]
    )
    parsed = parse_json_array_response(response.text)
    if not parsed.ok:
        raise ValueError(f"Personal memory extraction failed: {parsed.reason}")
    for item in parsed.items:
        if not isinstance(item, dict) or not all(
            item.get(key) for key in ("topic", "subject", "fact", "kind")
        ):
            raise ValueError("Personal memory extraction returned an invalid claim")
        if item["kind"] not in {"confirmed", "event", "inference", "uncertain"}:
            raise ValueError("Personal memory extraction returned an invalid kind")
    return parsed.items
