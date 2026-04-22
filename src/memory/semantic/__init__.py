"""Semantic memory façade exports."""

from __future__ import annotations

from .helpers import (
    l2_distance_to_cosine_similarity as _l2_distance_to_cosine_similarity,
)
from .helpers import normalize_embedding as _normalize_embedding
from .service import SemanticMemory

__all__ = ["SemanticMemory", "_l2_distance_to_cosine_similarity", "_normalize_embedding"]
