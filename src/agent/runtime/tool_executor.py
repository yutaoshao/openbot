"""Tool execution helpers for the main Agent."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.tools.effects import EFFECT_NONE, STATUS_ERROR, STATUS_TIMEOUT, tool_effect
from src.tools.registry import ToolResult
from src.tools.runtime import ToolExecutionContext, tool_execution_context

logger = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agent.state import TaskState
    from src.core.config import AgentConfig
    from src.tools.hooks import ToolHookManager
    from src.tools.registry import ToolRegistry


def summarize_tool_result(content: str) -> str:
    """Collapse verbose tool output into a compact task-state summary."""
    cleaned = " ".join(content.strip().split())
    return cleaned[:180] if cleaned else "(no output)"


async def execute_tool_call(
    registry: ToolRegistry | None,
    config: AgentConfig,
    hooks: ToolHookManager,
    name: str,
    arguments: dict[str, Any],
    *,
    conversation_id: str,
    platform: str,
    task_state: TaskState | None = None,
    timeout_override: float | None = None,
    checkpoint: Callable[[ToolResult, dict[str, Any]], None] | None = None,
) -> ToolResult:
    """Execute a single tool call by name."""
    if registry is None:
        return ToolResult(content="No tools available", is_error=True)

    tool = registry.get(name)
    if not tool:
        return ToolResult(content=f"Unknown tool: {name}", is_error=True)
    if not registry.is_execution_allowed(name):
        return _permission_result(name)

    configured_timeout = config.tool_timeout if config.tool_timeout > 0 else None
    timeout_candidates = [
        timeout
        for timeout in (configured_timeout, timeout_override)
        if timeout is not None and timeout > 0
    ]
    effective_timeout = min(timeout_candidates) if timeout_candidates else None

    tool_result: ToolResult | None = None
    effective_arguments = dict(arguments)

    def record_returned_result(result: ToolResult, effective: dict[str, Any]) -> None:
        nonlocal tool_result
        tool_result = result
        if checkpoint is not None:
            checkpoint(result, effective)

    try:
        pre_result = await hooks.before_execute(name, arguments, task_state)
        if not registry.is_execution_allowed(name):
            return _permission_result(name)
        effective_arguments = dict(pre_result.override_args or arguments)
        tool_result = await _run_tool(
            tool,
            effective_arguments,
            effective_timeout,
            conversation_id,
            platform,
            checkpoint=record_returned_result,
        )
        post_result = await hooks.after_execute(
            name,
            effective_arguments,
            tool_result,
            task_state,
        )
        result = _apply_hook_results(tool_result, pre_result, post_result)
    except TimeoutError:
        result = (
            _postprocessing_error_result(name, TimeoutError(), tool_result)
            if tool_result is not None
            else _timeout_result(name, effective_timeout)
        )
    except Exception as exc:
        result = (
            _postprocessing_error_result(name, exc, tool_result)
            if tool_result is not None
            else _exception_result(name, exc)
        )
    if checkpoint is not None:
        checkpoint(result, effective_arguments)
    return result


async def _run_tool(
    tool: Any,
    arguments: dict[str, Any],
    timeout: float | None,
    conversation_id: str,
    platform: str,
    *,
    checkpoint: Callable[[ToolResult, dict[str, Any]], None] | None = None,
) -> ToolResult:
    context = ToolExecutionContext(conversation_id=conversation_id, platform=platform)
    with tool_execution_context(context):
        if timeout is None:
            return await _execute_and_checkpoint(tool, arguments, checkpoint)
        return await asyncio.wait_for(
            _execute_and_checkpoint(tool, arguments, checkpoint), timeout=timeout
        )


async def _execute_and_checkpoint(
    tool: Any,
    arguments: dict[str, Any],
    checkpoint: Callable[[ToolResult, dict[str, Any]], None] | None,
) -> ToolResult:
    result = await tool.execute(arguments)
    # Capture before timeout/cancellation machinery hands the completed result
    # back to its caller, and before any asynchronous postprocessing begins.
    if checkpoint is not None:
        checkpoint(result, arguments)
    return result


def _apply_hook_results(tool_result: ToolResult, pre_result: Any, post_result: Any) -> ToolResult:
    metadata = dict(tool_result.metadata)
    combined_feedback = [*pre_result.feedback, *post_result.feedback]
    if combined_feedback:
        feedback_text = "\n".join(combined_feedback)
        metadata["hook_feedback"] = combined_feedback
        content = f"{tool_result.content}\n\nHarness feedback:\n{feedback_text}".strip()
    else:
        content = tool_result.content
    if post_result.activated_tools:
        metadata["activated_tools"] = list(post_result.activated_tools)
    return ToolResult(
        content=content,
        is_error=tool_result.is_error,
        metadata=metadata,
        effects=tool_result.effects,
    )


def _postprocessing_error_result(name: str, exc: Exception, result: ToolResult) -> ToolResult:
    logger.error("tool_postprocessing_failed", tool=name, error_type=type(exc).__name__)
    return ToolResult(
        content=f"{result.content}\n\nTool result postprocessing failed: {type(exc).__name__}",
        is_error=True,
        metadata={**result.metadata, "postprocessing_error": type(exc).__name__},
        effects=result.effects,
    )


def _timeout_result(name: str, timeout: float | None) -> ToolResult:
    timeout_text = f"{timeout:.2f}" if timeout is not None else "unknown"
    logger.warning(
        "tool_timeout",
        surface="operational",
        tool=name,
        timeout_s=round(timeout or 0.0, 3),
    )
    return ToolResult(
        content=f"Tool '{name}' timed out after {timeout_text}s",
        is_error=True,
        effects=(_tool_effect(name, STATUS_TIMEOUT),),
    )


def _permission_result(name: str) -> ToolResult:
    return ToolResult(
        content=f"Tool '{name}' is disabled or requires explicit execution authorization.",
        is_error=True,
        effects=(_tool_effect(name, STATUS_ERROR),),
    )


def _exception_result(name: str, exc: Exception) -> ToolResult:
    logger.exception(
        "tool_called",
        surface="operational",
        tool=name,
        status="exception",
        error=str(exc),
    )
    return ToolResult(
        content=f"Tool error: {exc}",
        is_error=True,
        effects=(_tool_effect(name, STATUS_ERROR),),
    )


def _tool_effect(name: str, status: str):
    return tool_effect(
        f"{name}.execute",
        EFFECT_NONE,
        status=status,
        target_type="tool",
        target=name,
        name=name,
    )
