"""Rebuild dossier projections or classify legacy knowledge without changing its text."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

from src.core.config import load_config
from src.infrastructure.database import Database
from src.infrastructure.embedding import EmbeddingService, NullEmbeddingService
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import ModelGateway
from src.infrastructure.storage import Storage
from src.memory.personal_documents import _write_if_unchanged
from src.memory.personal_profile import PersonalProfile
from src.memory.personal_retrieval import PersonalRetrieval
from src.memory.structured_json import parse_json_array_response

_CLASSIFY = """仅分类旧记忆的归属，不核实真伪，也不改写内容。
每项输出 {"index": 输入序号, "memory_type": 分类}，组成 JSON 数组。
分类只能为 general、personal_legacy、legacy_unreviewed。
general：不依赖本用户/其亲友/宠物/项目当前状态的一般知识、公共概念、操作方法。
personal_legacy：个人信息、习惯、偏好、计划、特定事件、用户项目/环境的具体状态。
混合一般知识和个人信息也归 personal_legacy。无法确定归 legacy_unreviewed。
禁止把猜测或旧总结提升为个人确认事实，此操作仅决定旧条目是否参与一般知识检索。
完整覆盖输入每项一次，不能遗漏、增加或重复 index。
"""


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


async def audit_legacy(storage: Storage, gateway: ModelGateway, report: Path) -> dict:
    old_report = report.read_text() if report.exists() else ""
    results = json.loads(old_report) if old_report else {}
    items, offset = [], 0
    while batch := await storage.knowledge.list_all(limit=500, offset=offset):
        items.extend(batch)
        offset += len(batch)
    pending = [
        item
        for item in items
        if item.get("memory_type") != "general"
        and results.get(item["id"], {}).get("sha256") != _fingerprint(item["content"])
    ]
    semaphore = asyncio.Semaphore(2)

    async def classify(batch: list[dict]) -> None:
        async with semaphore:
            response = await gateway.chat(
                [
                    {"role": "system", "content": _CLASSIFY},
                    {
                        "role": "user",
                        "content": json.dumps(
                            [
                                {"index": index, "content": item["content"]}
                                for index, item in enumerate(batch)
                            ],
                            ensure_ascii=False,
                        ),
                    },
                ]
            )
            parsed = parse_json_array_response(response.text)
            valid = {"general", "personal_legacy", "legacy_unreviewed"}
            if (
                not parsed.ok
                or len(parsed.items) != len(batch)
                or any(
                    not isinstance(item, dict)
                    or type(item.get("index")) is not int
                    or item.get("memory_type") not in valid
                    for item in parsed.items
                )
                or {item["index"] for item in parsed.items} != set(range(len(batch)))
            ):
                raise ValueError("Legacy classification did not cover its complete input batch")
            for label in parsed.items:
                item = batch[label["index"]]
                results[item["id"]] = {
                    "memory_type": label["memory_type"],
                    "sha256": _fingerprint(item["content"]),
                }
            before = report.read_text() if report.exists() else ""
            _write_if_unchanged(report, before, json.dumps(results, ensure_ascii=False, indent=2))
            print(f"Legacy audit: {len(results)}/{len(items)}", flush=True)

    outcomes = await asyncio.gather(
        *(classify(pending[start : start + 160]) for start in range(0, len(pending), 160)),
        return_exceptions=True,
    )
    errors = [item for item in outcomes if isinstance(item, BaseException)]
    if errors:
        raise RuntimeError(
            f"Legacy audit has {len(errors)} failed batches; rerun to resume"
        ) from errors[0]
    counts: dict[str, int] = {}
    for item in items:
        result = results.get(item["id"])
        if result is None or result["sha256"] != _fingerprint(item["content"]):
            continue
        current = await storage.knowledge.get(item["id"])
        if current is None or _fingerprint(current["content"]) != result["sha256"]:
            raise RuntimeError(f"Knowledge changed during classification: {item['id']}")
        await storage.knowledge.update(item["id"], memory_type=result["memory_type"])
        counts[result["memory_type"]] = counts.get(result["memory_type"], 0) + 1
    return counts


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["rebuild", "audit-legacy"])
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    if args.operation == "audit-legacy":
        backup = Path("data/personal_memory/_migration/four-layer-before.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            with (
                sqlite3.connect(config.storage.db_path) as source,
                sqlite3.connect(backup) as target,
            ):
                source.backup(target)
    db = Database(config.storage, embedding_dimensions=config.embedding.dimensions)
    await db.initialize()
    try:
        storage = Storage(db)
        if args.operation == "audit-legacy":
            gateway = ModelGateway(config.model, EventBus(), config.agent)
            result = await audit_legacy(
                storage, gateway, Path("data/personal_memory/_migration/legacy-types.json")
            )
            print(json.dumps(result, ensure_ascii=False))
        else:
            embedding = (
                EmbeddingService(config.embedding)
                if config.embedding.enabled
                else NullEmbeddingService()
            )
            index = PersonalRetrieval(
                PersonalProfile(), index=storage.personal_index, embedding=embedding
            )
            chunks = await index.rebuild()
            print(
                json.dumps(
                    {
                        "documents": len(index.profile.documents()),
                        "chunks": len(chunks),
                        "vectors": sum(bool(item["embedding"]) for item in chunks),
                    }
                )
            )
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
