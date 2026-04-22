from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.agent.agent import Agent
from src.agent.delegation import SubAgent
from src.core.config import AgentConfig
from src.tools.registry import ToolRegistry, ToolResult


class _HangingTool:
    @property
    def name(self) -> str:
        return "hanging_tool"

    @property
    def description(self) -> str:
        return "Sleeps longer than the configured timeout."

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    @property
    def category(self) -> str:
        return "test"

    async def execute(self, args: dict[str, object]) -> ToolResult:
        await asyncio.sleep(0.05)
        return ToolResult(content="completed")


@dataclass
class _FakeEventBus:
    async def publish(self, event_name: str, payload: dict[str, object]) -> None:
        return None


async def test_agent_tool_timeout_respects_remaining_task_budget() -> None:
    registry = ToolRegistry()
    registry.register(_HangingTool())
    agent = Agent(
        model_gateway=object(),
        event_bus=_FakeEventBus(),
        config=AgentConfig(tool_timeout=10),
        tool_registry=registry,
    )

    result = await agent._execute_tool(
        "hanging_tool",
        {},
        conversation_id="conv-1",
        platform="web",
        timeout_override=0.01,
    )

    assert result.is_error
    assert "timed out" in result.content


async def test_sub_agent_tool_timeout_returns_tool_error() -> None:
    registry = ToolRegistry()
    registry.register(_HangingTool())
    delegator = SubAgent(
        model_gateway=object(),
        event_bus=_FakeEventBus(),
        config=AgentConfig(tool_timeout=0.01),
        tool_registry=registry,
    )

    result = await delegator._execute_tool("hanging_tool", {})

    assert result.is_error
    assert "timed out" in result.content
