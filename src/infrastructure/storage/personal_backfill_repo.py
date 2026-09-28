"""Persistence for offline review and apply progress, separate from online cursors."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class PersonalBackfillRepo:
    """Use the existing backfill tables without changing their schema or commit boundaries."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def source_messages(db_path: Path) -> list[dict]:
        with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT id, conversation_id, role, content, timestamp FROM messages "
                    "ORDER BY timestamp, created_at, id"
                )
            ]

    def turns(self) -> dict[str, dict]:
        self._connection.row_factory = sqlite3.Row
        return {
            row["message_id"]: dict(row)
            for row in self._connection.execute("SELECT * FROM personal_backfill_turns")
        }

    def document_revisions(self) -> dict[str, str]:
        return dict(
            self._connection.execute("SELECT path, revision FROM personal_backfill_documents")
        )

    def save_document_revision(self, name: str, revision: str) -> None:
        self._connection.execute(
            """INSERT INTO personal_backfill_documents (path, revision) VALUES (?, ?)
            ON CONFLICT(path) DO UPDATE SET revision=excluded.revision""",
            (name, revision),
        )
        self._connection.commit()

    def save_turn(
        self,
        *,
        message_id: str,
        source: str,
        timestamp: str,
        aliases: tuple[str, ...],
        status: str,
        claims: list[dict],
        error: str = "",
    ) -> None:
        self._connection.execute(
            """INSERT INTO personal_backfill_turns
                (message_id, source, statement_at, source_aliases,
                 status, claims, error, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET status=excluded.status,
                claims=excluded.claims, error=excluded.error, updated_at=excluded.updated_at""",
            (
                message_id,
                source,
                timestamp,
                json.dumps(aliases, ensure_ascii=False),
                status,
                json.dumps(claims, ensure_ascii=False),
                error,
                datetime.now(UTC).isoformat(),
            ),
        )

    def commit(self) -> None:
        self._connection.commit()
