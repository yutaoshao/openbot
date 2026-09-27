"""Offer unresolved event follow-ups and record only acknowledged deliveries."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from src.core.logging import get_logger
from src.memory.structured_json import parse_json_array_response

logger = get_logger(__name__)
_NO_FOLLOWUP = "本次没有允许的历史事件追问；请直接回答用户问题，不主动催问旧事。"


class PersonalFollowups:
    def __init__(self, *, profile: Any, repository: Any, gateway: Any) -> None:
        self.profile = profile
        self.repository = repository
        self.gateway = gateway
        self._lock = asyncio.Lock()

    async def confirm_delivery(self, conversation_id: str, content: str, delivery_id: str) -> None:
        asked = await self.repository.asked()
        candidates = [
            self._candidate(event)
            for event in self.profile.events()
            if event.can_follow_up and (event.id, event.field) not in asked
        ]
        if not candidates:
            return
        await self.repository.record_delivery(
            delivery_id=f"{conversation_id}:{delivery_id}",
            conversation_id=conversation_id,
            content=content,
            candidates=candidates,
        )
        await self._process_deliveries()

    async def _process_deliveries(self) -> bool:
        async with self._lock:
            for receipt in await self.repository.pending():
                try:
                    selected = await self._select(
                        "找出已交付答复中实际向用户询问后续的候选事件。"
                        "陈述、引用别人问题、回答用户的问题不算追问；没有问号的自然询问也算。"
                        "返回已问的候选ID数组。",
                        {"delivered_text": receipt["content"], "candidates": receipt["candidates"]},
                    )
                    asked = [item for item in receipt["candidates"] if item["event_id"] in selected]
                    await self.repository.finish_delivery(receipt, asked)
                except Exception:
                    logger.exception(
                        "personal_followups.delivery_classification_failed",
                        delivery_id=receipt["id"],
                    )
                    return False
        return True

    async def context(self, query: str, *, profile_context: str, history_context: str) -> str:
        if not await self._process_deliveries():
            return _NO_FOLLOWUP + "交付记录尚待核实，避免重复询问。"
        asked = await self.repository.asked()
        events = self.profile.events()
        for event in events:
            if event.status in {"done", "cancelled"}:
                await self.repository.resolve(event.id, event.source)
        candidates = [
            self._candidate(event)
            for event in events
            if event.can_follow_up
            and event.id in profile_context
            and (event.id, event.field) not in asked
        ]
        if not candidates or not history_context:
            return _NO_FOLLOWUP
        try:
            selected = await self._select(
                "判断当前话题是否自然需要追问候选中的未知结果。先检查所附原始历史："
                "已经交代结果、已取消、只是普通咨询、话题无关或证据不足时都不要选。"
                "只有明确计划/正在经历且结果确实未知的相关事件可选。返回最多一个候选ID的数组。",
                {"query": query, "candidates": candidates, "original_history": history_context},
            )
        except Exception:
            logger.exception("personal_followups.eligibility_failed")
            return _NO_FOLLOWUP
        eligible = [item for item in candidates if item["event_id"] in selected][:1]
        if not eligible:
            return _NO_FOLLOWUP
        logger.info("personal_followups.offered", events=[item["event_id"] for item in eligible])
        return (
            "可选的相关追问（已经检查历史并确认尚未问过；不必为了追问而追问；"
            "如采用请原样使用问句，且只问这一项）：\n" + eligible[0]["question"]
        )

    async def _select(self, instruction: str, payload: dict) -> set[str]:
        response = await self.gateway.chat(
            [
                {"role": "system", "content": instruction + ' 格式：[{"event_id":"候选ID"}] 或 []'},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        parsed = parse_json_array_response(response.text)
        allowed = {item["event_id"] for item in payload["candidates"]}
        if not parsed.ok or any(
            not isinstance(item, dict) or item.get("event_id") not in allowed
            for item in parsed.items
        ):
            raise ValueError("Invalid follow-up classification result")
        return {item["event_id"] for item in parsed.items}

    @staticmethod
    def _candidate(event: Any) -> dict:
        return {
            "event_id": event.id,
            "field": event.field,
            "question": event.question,
            "subject": event.subject,
            "event": event.name,
            "status": event.status,
        }
