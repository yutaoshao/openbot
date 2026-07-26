"""Immutable inputs and outputs for the ReAct loop executor."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from src.agent.turn_outcome import TurnOutcome
    from src.infrastructure.model_gateway import StreamChunk

    from .turn_request import TurnRequest


@dataclass(frozen=True, kw_only=True)
class TurnLoopContext:
    """Immutable dependencies and prepared input for one loop."""

    agent: Any
    request: TurnRequest
    trace_context: Any
    messages: tuple[dict[str, Any], ...]
    route_decision: Any
    contract: Any
    project_root: Path | None
    clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True, kw_only=True)
class TurnLoopSnapshot:
    """Immutable execution facts captured when the loop stops."""

    request: TurnRequest
    contract: Any
    project_root: Path | None
    iterations: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    final_model: str
    tool_calls: tuple[dict[str, Any], ...]


@dataclass(frozen=True, kw_only=True)
class LoopCompletion:
    """Raw loop outcome plus the facts needed for finalization."""

    outcome: TurnOutcome
    snapshot: TurnLoopSnapshot
    pending_text: str = ""
    pending_chunks: tuple[StreamChunk, ...] = ()
