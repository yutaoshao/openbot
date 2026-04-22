"""Typed repository layer on top of SQLite."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._base import json_dumps, json_loads
from .conversations_repo import ConversationRepo
from .identities_repo import UserIdentityRepo
from .knowledge_repo import KnowledgeRepo
from .logs_repo import LogRepo
from .messages_repo import MessageRepo
from .metrics_repo import MetricsRepo
from .preferences_repo import PreferenceRepo
from .schedules_repo import ScheduleRepo

if TYPE_CHECKING:
    from src.infrastructure.database import Database


class Storage:
    """Top-level data access object aggregating all repositories."""

    def __init__(self, db: Database) -> None:
        self.conversations = ConversationRepo(db)
        self.messages = MessageRepo(db)
        self.knowledge = KnowledgeRepo(db)
        self.preferences = PreferenceRepo(db)
        self.user_identities = UserIdentityRepo(db)
        self.metrics = MetricsRepo(db)
        self.schedules = ScheduleRepo(db)
        self.logs = LogRepo(db)


_json_dumps = json_dumps
_json_loads = json_loads

__all__ = [
    "ConversationRepo",
    "KnowledgeRepo",
    "LogRepo",
    "MessageRepo",
    "MetricsRepo",
    "PreferenceRepo",
    "ScheduleRepo",
    "Storage",
    "UserIdentityRepo",
    "_json_dumps",
    "_json_loads",
]
