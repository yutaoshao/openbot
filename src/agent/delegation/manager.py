"""Sub-agent delegation system.

Allows the main agent to decompose complex tasks and delegate subtasks
to worker agents that run in parallel.  Workers cannot delegate further
(single-level delegation only).

Key design:
- Workers share the same ModelGateway but get a scoped ToolRegistry.
- Results are aggregated and returned to the main agent as context.
- Failed subtasks are reported but do not abort the entire delegation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger

if TYPE_CHECKING:
    from src.core.config import AgentConfig
    from src.infrastructure.event_bus import EventBus
    from src.infrastructure.model_gateway import ModelGateway
    from src.tools.registry import ToolRegistry

logger = get_logger(__name__)


@dataclass
class SubTaskResult:
    """Result from a single sub-agent execution."""

    task_id: str
    description: str
    content: str
    success: bool = True
    error: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


@dataclass
class DelegationResult:
    """Aggregated result from all sub-agents."""

    subtask_results: list[SubTaskResult] = field(default_factory=list)
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_latency_ms: int = 0

    @property
    def all_succeeded(self) -> bool:
        return all(r.success for r in self.subtask_results)

    def to_context_message(self) -> str:
        """Format results as context for the main agent."""
        parts: list[str] = ["Sub-agent results:"]
        for r in self.subtask_results:
            status = "OK" if r.success else f"FAILED: {r.error}"
            parts.append(f"\n## Task: {r.description} [{status}]")
            parts.append(r.content[:2000] if r.success else "")
        return "\n".join(parts)


class SubAgent:
    """Manages sub-agent delegation and parallel execution.

    Usage from the main agent's tool or run loop::

        delegator = SubAgent(model_gateway, event_bus, config, tool_registry)
        result = await delegator.delegate([
            {"description": "Search for X", "tools": ["web_search"]},
            {"description": "Analyze Y", "tools": ["code_executor"]},
        ])
        context = result.to_context_message()
    """

    def __init__(
        self,
        model_gateway: ModelGateway,
        event_bus: EventBus,
        config: AgentConfig,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self._gateway = model_gateway
        self._event_bus = event_bus
        self._config = config
        self._tool_registry = tool_registry

    async def delegate(
        self,
        subtasks: list[dict[str, Any]],
        *,
        max_concurrent: int = 5,
        system_prompt: str = "",
    ) -> DelegationResult:
        """Execute subtasks in parallel via worker agents.

        Args:
            subtasks: List of dicts with keys:
                - description (str, required): What the worker should do
                - tools (list[str], optional): Tool names the worker can use
                - context (str, optional): Extra context for the worker
            max_concurrent: Maximum parallel workers.
            system_prompt: Base system prompt for workers.

        Returns:
            Aggregated DelegationResult.
        """
        if not subtasks:
            return DelegationResult()

        logger.info("sub_agent.delegating", subtask_count=len(subtasks))

        await self._event_bus.publish(
            "sub_agent.delegate.start",
            {
                "subtask_count": len(subtasks),
                "descriptions": [t.get("description", "") for t in subtasks],
            },
        )

        # Run with concurrency limit via semaphore
        semaphore = asyncio.Semaphore(max_concurrent)
        tasks = [
            self._run_worker(i, subtask, semaphore, system_prompt)
            for i, subtask in enumerate(subtasks)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Aggregate
        delegation = DelegationResult()
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                sub_result = SubTaskResult(
                    task_id=f"subtask_{i}",
                    description=subtasks[i].get("description", ""),
                    content="",
                    success=False,
                    error=str(result),
                )
            else:
                sub_result = result
            delegation.subtask_results.append(sub_result)
            delegation.total_tokens_in += sub_result.tokens_in
            delegation.total_tokens_out += sub_result.tokens_out

        succeeded = sum(1 for r in delegation.subtask_results if r.success)
        failed = len(delegation.subtask_results) - succeeded

        await self._event_bus.publish(
            "sub_agent.delegate.complete",
            {
                "subtask_count": len(subtasks),
                "succeeded": succeeded,
                "failed": failed,
                "total_tokens_in": delegation.total_tokens_in,
                "total_tokens_out": delegation.total_tokens_out,
            },
        )

        logger.info(
            "sub_agent.delegation_complete",
            total=len(subtasks),
            succeeded=succeeded,
            failed=failed,
        )

        return delegation

    async def _run_worker(
        self,
        index: int,
        subtask: dict[str, Any],
        semaphore: asyncio.Semaphore,
        base_system_prompt: str,
    ) -> SubTaskResult:
        """Run a single worker agent for one subtask."""
        import time

        description = subtask.get("description", f"Subtask {index}")
        allowed_tools = subtask.get("tools")
        extra_context = subtask.get("context", "")
        task_id = f"subtask_{index}"

        # Build scoped tool registry
        scoped_tools = self._build_scoped_tools(allowed_tools)

        # Build worker system prompt
        worker_prompt = self._build_worker_prompt(
            base_system_prompt,
            description,
            extra_context,
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": worker_prompt},
            {"role": "user", "content": description},
        ]

        tools = scoped_tools.get_schemas() if scoped_tools else None

        async with semaphore:
            start = time.monotonic()
            logger.info(
                "sub_agent.worker_start",
                task_id=task_id,
                description=description[:80],
            )

            try:
                response = await self._worker_loop(messages, tools)
                latency_ms = int((time.monotonic() - start) * 1000)

                logger.info(
                    "sub_agent.worker_done",
                    task_id=task_id,
                    latency_ms=latency_ms,
                )

                return SubTaskResult(
                    task_id=task_id,
                    description=description,
                    content=response.text,
                    success=True,
                    tokens_in=response.usage.tokens_in,
                    tokens_out=response.usage.tokens_out,
                    latency_ms=latency_ms,
                )

            except Exception as e:
                latency_ms = int((time.monotonic() - start) * 1000)
                logger.exception(
                    "sub_agent.worker_failed",
                    task_id=task_id,
                )
                return SubTaskResult(
                    task_id=task_id,
                    description=description,
                    content="",
                    success=False,
                    error=str(e),
                    latency_ms=latency_ms,
                )

    async def _worker_loop(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> Any:
        """Simplified ReAct loop for a worker (no streaming, no memory).

        Workers are intentionally limited:
        - No conversation memory
        - No further delegation (single-level only)
        - Reduced max_iterations (half of main agent)
        """
        max_iter = max(1, self._config.max_iterations // 2)

        for _iteration in range(max_iter):
            response = await self._gateway.chat(
                messages=messages,
                tools=tools,
            )

            if not response.has_tool_calls:
                return response

            # Execute tool calls
            messages.append(response.to_assistant_message())
            for tc in response.tool_calls:
                tool_result = await self._execute_tool(tc.name, tc.arguments)
                messages.append(tool_result.to_message(tc.id))

        # Max iterations reached — return last response
        return await self._gateway.chat(messages=messages, tools=None)

    async def _execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Execute a tool (worker-scoped)."""
        from src.tools.registry import ToolResult

        if not self._tool_registry:
            return ToolResult(content="No tools available", is_error=True)

        tool = self._tool_registry.get(name)
        if not tool:
            return ToolResult(content=f"Unknown tool: {name}", is_error=True)

        tool_timeout = self._config.tool_timeout if self._config.tool_timeout > 0 else None

        try:
            if tool_timeout is None:
                return await tool.execute(arguments)
            return await asyncio.wait_for(tool.execute(arguments), timeout=tool_timeout)
        except TimeoutError:
            logger.warning(
                "sub_agent.tool_timeout",
                tool=name,
                timeout_s=round(tool_timeout or 0.0, 3),
            )
            return ToolResult(
                content=f"Tool '{name}' timed out after {tool_timeout:.2f}s",
                is_error=True,
            )
        except Exception as e:
            logger.warning("sub_agent.tool_error", tool=name, error=str(e))
            return ToolResult(content=f"Tool error: {e}", is_error=True)

    def _build_scoped_tools(
        self,
        allowed_names: list[str] | None,
    ) -> ToolRegistry | None:
        """Build a ToolRegistry containing only the specified tools."""
        if not self._tool_registry:
            return None

        if allowed_names is None:
            return self._tool_registry

        from src.tools.registry import ToolRegistry

        scoped = ToolRegistry()
        for name in allowed_names:
            tool = self._tool_registry.get(name)
            if tool:
                scoped.register(tool)
        return scoped

    @staticmethod
    def _build_worker_prompt(
        base: str,
        description: str,
        extra_context: str,
    ) -> str:
        """Build the system prompt for a worker agent."""
        parts = [
            base or "You are a focused worker agent. Complete the assigned task concisely.",
            "",
            "IMPORTANT: You are a worker agent. You CANNOT delegate tasks.",
            "Focus solely on your assigned task and report findings clearly.",
        ]
        if extra_context:
            parts.append(f"\nContext:\n{extra_context}")
        return "\n".join(parts)
