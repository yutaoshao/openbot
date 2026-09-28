"""Stage, review, and merge historical personal memories from original speech."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from pathlib import Path

from src.core.config import load_config
from src.infrastructure.database import Database
from src.infrastructure.event_bus import EventBus
from src.infrastructure.model_gateway import ModelGateway
from src.memory.personal_backfill import apply_history, inventory, review_report, stage_history
from src.memory.personal_profile import PersonalProfile


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["inventory", "stage", "apply"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()
    config = load_config(args.config)
    db_path = Path(config.storage.db_path)
    turns, coverage = inventory(db_path, Path("data/conversations"))
    if args.phase == "inventory":
        print(json.dumps(coverage, ensure_ascii=False, indent=2))
        return
    db = Database(config.storage, embedding_dimensions=config.embedding.dimensions)
    await db.initialize()
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            profile = PersonalProfile()
            if args.phase == "stage":
                result = await stage_history(
                    conn, turns, profile, ModelGateway(config.model, EventBus(), config.agent),
                    batch_size=args.batch_size, limit=args.limit,
                )
            else:
                result = await apply_history(conn, turns, profile)
            report = Path("data/personal_memory/_migration/completeness-review.jsonl")
            review_report(conn, turns, report)
            print(json.dumps({
                "coverage": coverage, "status": result,
                "unprocessed": len(turns) - sum(result.values()),
                "report": str(report),
                "uncertain": str(report.with_name("completeness-uncertain.jsonl")),
                "failures": str(report.with_name("completeness-failures.jsonl")),
            }, ensure_ascii=False, default=dict))
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
