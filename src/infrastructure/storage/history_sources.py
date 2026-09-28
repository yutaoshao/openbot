"""Read original conversation evidence from archives and SQLite."""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from src.core.logging import get_logger

logger = get_logger(__name__)

if TYPE_CHECKING:
    from pathlib import Path


class HistorySources:
    """Keep the archive and database formats behind one source boundary."""

    def __init__(self, root: Path, db_path: Path) -> None:
        self.root = root
        self.db_path = db_path

    def signature(self) -> tuple[tuple, list[Path]]:
        files = sorted(self.root.glob("*/*/*.jsonl"))
        watched = [*files, self.db_path, self.db_path.with_name(self.db_path.name + "-wal")]
        signature = tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in watched
            if path.is_file()
        )
        return signature, files

    def archived(self, files: list[Path]):
        for path in files:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("personal_history.invalid_json", path=str(path), line=number)
                    continue
                yield f"{path}:{number}", item

    def messages(self) -> list[dict]:
        if not self.db_path.is_file():
            return []
        with sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            return [
                dict(row) for row in conn.execute("SELECT * FROM messages ORDER BY timestamp, id")
            ]
