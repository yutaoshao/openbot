from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.agent.coordination import UserExecutionCoordinator
from src.agent.runtime.tool_calls import _record_tool_context
from src.agent.state import TaskState
from src.agent.verification import verify_final_response
from src.tools.builtin.tool_search import ToolSearchTool
from src.tools.effects import ToolEffect
from src.tools.registry import CORE_VISIBILITY, DEFERRED_VISIBILITY, ToolRegistry, ToolResult


class _DummyTool:
    def __init__(self, name: str, description: str) -> None:
        self._name = name
        self._description = description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict[str, object]:
        return {"type": "object", "properties": {}}

    @property
    def category(self) -> str:
        return "misc"

    async def execute(self, args: dict[str, object]):
        raise NotImplementedError


def test_tool_registry_only_exposes_core_tools_until_deferred_activated() -> None:
    registry = ToolRegistry()
    registry.register(_DummyTool("core_tool", "Core tool"), visibility=CORE_VISIBILITY)
    registry.register(
        _DummyTool("deferred_tool", "Handles alerts"),
        visibility=DEFERRED_VISIBILITY,
        keywords=["alert", "alarm"],
    )

    default_schemas = registry.get_schemas(active_names=registry.get_default_active_names())
    assert [schema["name"] for schema in default_schemas] == ["core_tool"]

    matched = registry.match_deferred("check alert status")
    assert matched == {"deferred_tool"}
    active_schemas = registry.get_schemas(
        active_names=registry.get_default_active_names() | matched,
    )
    assert {schema["name"] for schema in active_schemas} == {
        "core_tool",
        "deferred_tool",
    }


async def test_tool_search_returns_activation_metadata() -> None:
    registry = ToolRegistry()
    registry.register(
        _DummyTool("alarm_tool", "Inspect on-call alerts"),
        visibility=DEFERRED_VISIBILITY,
        keywords=["alert", "alarm"],
    )
    search_tool = ToolSearchTool(registry)

    result = await search_tool.execute({"query": "alert"})

    assert result.is_error is False
    assert result.effects[0].effect == "tools_discovered"
    assert result.effects[0].details["activated_tools"] == ("alarm_tool",)


def test_loaded_skill_effect_is_protected_context() -> None:
    protected: list[tuple[str, str, str]] = []

    class ConversationManager:
        def record_tool_event(self, *_args, **_kwargs) -> None:
            return None

        def protect_context(self, conversation_id: str, key: str, content: str) -> None:
            protected.append((conversation_id, key, content))

    tool_result = ToolResult(
        content="skill body",
        effects=(
            ToolEffect(
                action="skill.load",
                effect="skill_loaded",
                status="completed",
                target_type="skill",
                target="demo",
                name="load_skill",
            ),
        ),
    )
    agent = SimpleNamespace(conversation_manager=ConversationManager())
    tool_call = SimpleNamespace(name="load_skill")

    _record_tool_context(
        agent,
        conversation_id="conv-1",
        tool_call=tool_call,
        tool_result=tool_result,
    )

    assert protected == [("conv-1", "skill:demo", "skill body")]


def test_verify_final_response_rewrites_vague_completion() -> None:
    task_state = TaskState(objective="Investigate webhook failure")
    task_state.record_tool_event("web_search", "Found failing callback docs", is_error=False)
    task_state.record_tool_event("web_fetch", "Read webhook troubleshooting guide", is_error=False)

    content, rewritten = verify_final_response(
        "分析完成",
        tool_calls_made=[{"name": "web_search"}],
        task_state=task_state,
    )

    assert rewritten is True
    assert "本轮未完成" in content
    assert "Objective:" not in content
    assert "Evidence:" not in content


async def test_user_execution_coordinator_serializes_same_user() -> None:
    coordinator = UserExecutionCoordinator()
    order: list[str] = []

    async def worker(name: str, delay_ms: int) -> int:
        async with coordinator.serialize("user-1") as waited_ms:
            order.append(f"start:{name}")
            await asyncio.sleep(delay_ms / 1000)
            order.append(f"end:{name}")
            return int(waited_ms)

    first, second = await asyncio.gather(
        worker("a", 50),
        worker("b", 0),
    )

    assert order == ["start:a", "end:a", "start:b", "end:b"]
    assert first == 0
    assert second >= 40
