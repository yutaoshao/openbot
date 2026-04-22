"""Episodic memory façade exports."""

from __future__ import annotations

from .helpers import normalize_embedding as _normalize_embedding
from .service import EpisodicMemory

__all__ = ["EpisodicMemory", "_normalize_embedding"]
