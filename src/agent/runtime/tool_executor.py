"""Tool execution helpers for the main Agent."""

from __future__ import annotations

import asyncio
from typing import Any

from src.core.logging import get_logger
from src.tools.runtime import ToolExecutionContext, tool_execution_context

logger = get_logger(__name__)


def summarize_tool_result(content: str) -> str:
    """Collapse verbose tool output into a compact task-state summary."""
    cleaned = " ".join(content.strip().split())
    return cleaned[:180] if cleaned else "(no output)"


async def execute_tool_call(
    agent: Any,
    name: str,
    arguments: dict[str, Any],
    *,
    conversation_id: str,
    platform: str,
    task_state: Any = None,
    timeout_override: float | None = None,
):
    """Execute a single tool call by name."""
    from src.tools.registry import ToolResult

    if not agent.tool_registry:
        return ToolResult(content="No tools available", is_error=True)

    tool = agent.tool_registry.get(name)
    if not tool:
        return ToolResult(content=f"Unknown tool: {name}", is_error=True)

    configured_timeout = agent.config.tool_timeout if agent.config.tool_timeout > 0 else None
    timeout_candidates = [
        timeout
        for timeout in (configured_timeout, timeout_override)
        if timeout is not None and timeout > 0
    ]
    effective_timeout = min(timeout_candidates) if timeout_candidates else None

    try:
        pre_result = await agent._tool_hooks.before_execute(  # noqa: SLF001
            name,
            arguments,
            task_state,
        )
        effective_arguments = dict(pre_result.override_args or arguments)
        with tool_execution_context(
            ToolExecutionContext(
                conversation_id=conversation_id,
                platform=platform,
            )
        ):
            if effective_timeout is None:
                tool_result = await tool.execute(effective_arguments)
            else:
                tool_result = await asyncio.wait_for(
                    tool.execute(effective_arguments),
                    timeout=effective_timeout,
                )
        post_result = await agent._tool_hooks.after_execute(  # noqa: SLF001
            name,
            effective_arguments,
            tool_result,
            task_state,
        )
        metadata = dict(tool_result.metadata)
        combined_feedback = [*pre_result.feedback, *post_result.feedback]
        if combined_feedback:
            feedback_text = "\n".join(combined_feedback)
            tool_result.content = (
                f"{tool_result.content}\n\nHarness feedback:\n{feedback_text}"
            ).strip()
            metadata["hook_feedback"] = combined_feedback
        if post_result.activated_tools:
            metadata["activated_tools"] = list(post_result.activated_tools)
        tool_result.metadata = metadata
        return tool_result
    except TimeoutError:
        logger.warning(
            "tool_timeout",
            surface="operational",
            tool=name,
            timeout_s=round(effective_timeout or 0.0, 3),
        )
        return ToolResult(
            content=f"Tool '{name}' timed out after {effective_timeout:.2f}s",
            is_error=True,
        )
    except Exception as exc:
        logger.exception(
            "tool_called",
            surface="operational",
            tool=name,
            status="exception",
            error=str(exc),
        )
        return ToolResult(content=f"Tool error: {exc}", is_error=True)
