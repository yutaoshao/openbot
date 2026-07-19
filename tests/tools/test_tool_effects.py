from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agent.skills import LoadSkillTool, SkillMeta
from src.tools.builtin.bash_tool import BashTool
from src.tools.builtin.code_executor import CodeExecutorTool
from src.tools.builtin.deep_research import DeepResearchTool
from src.tools.builtin.file_mutation_tools import CreateFileTool
from src.tools.builtin.schedule_manager import ScheduleManagerTool
from src.tools.builtin.tool_search import ToolSearchTool
from src.tools.builtin.web_fetch import WebFetchTool
from src.tools.builtin.web_search import WebSearchTool
from src.tools.file_mutation_service import FileMutationService
from src.tools.registry import DEFERRED_VISIBILITY, ToolRegistry, ToolResult
from src.tools.runtime import ToolExecutionContext, tool_execution_context


class _FakeScheduler:
    timezone_name = "Asia/Shanghai"

    def __init__(self) -> None:
        self.items = {
            "sched-1": {
                "id": "sched-1",
                "name": "Daily",
                "prompt": "old",
                "cron": "0 8 * * *",
                "status": "active",
                "next_run_at": None,
            }
        }

    async def create_schedule(self, **fields: Any) -> dict[str, Any]:
        item = {"id": "sched-2", "next_run_at": None, **fields}
        self.items[item["id"]] = item
        return item

    async def list_schedules(self, **_: Any) -> list[dict[str, Any]]:
        return list(self.items.values())

    async def get_schedule(self, schedule_id: str) -> dict[str, Any] | None:
        return self.items.get(schedule_id)

    async def update_schedule(self, schedule_id: str, **fields: Any) -> dict[str, Any] | None:
        item = self.items.get(schedule_id)
        if item is None:
            return None
        item.update(fields)
        return item

    async def delete_schedule(self, schedule_id: str) -> None:
        self.items.pop(schedule_id, None)


class _FakeResearchReport:
    rounds_executed = 1
    total_searches = 2
    findings = ("finding",)
    sources = ("source",)
    saturated = False
    latency_ms = 12
    synthesis = "research result"


class _FakeDeepResearch:
    async def research(self, topic: str, *, max_rounds: int) -> _FakeResearchReport:
        return _FakeResearchReport()


class _FakeSkillRegistry:
    def __init__(self) -> None:
        self._skills = {
            "demo": SkillMeta(
                name="demo",
                description="Demo skill",
                path=Path("/tmp/demo/SKILL.md"),
            )
        }

    def load(self, skill_name: str) -> str | None:
        return "skill body" if skill_name == "demo" else None

    def list_references(self, skill_name: str) -> list[str]:
        return ["references/a.md"] if skill_name == "demo" else []


def _effect(result: ToolResult):
    assert len(result.effects) == 1
    return result.effects[0]


async def test_create_file_returns_verified_file_written_effect(tmp_path) -> None:
    result = await CreateFileTool(FileMutationService(tmp_path)).execute(
        {"path": "notes/example.md", "content": "hello"}
    )

    effect = _effect(result)
    assert effect.action == "file.create"
    assert effect.effect == "file_written"
    assert effect.target_type == "file"
    assert effect.target == "notes/example.md"
    assert effect.details["file_mutation"]["postcondition"] == "verified"


async def test_schedule_manager_update_returns_schedule_updated_effect() -> None:
    scheduler = _FakeScheduler()
    result = await ScheduleManagerTool(lambda: scheduler).execute(
        {"operation": "update", "schedule_id": "sched-1", "prompt": "new"}
    )

    effect = _effect(result)
    assert effect.action == "schedule.update"
    assert effect.effect == "schedule_updated"
    assert effect.target_type == "schedule"
    assert effect.target == "sched-1"


async def test_bash_returns_command_executed_effect(tmp_path) -> None:
    result = await BashTool(root=tmp_path).execute(
        {"description": "print", "command": "printf hello"}
    )

    effect = _effect(result)
    assert effect.action == "command.execute"
    assert effect.effect == "command_executed"
    assert effect.status == "completed"


async def test_code_executor_returns_code_executed_effect() -> None:
    result = await CodeExecutorTool().execute({"code": "print('hello')"})

    effect = _effect(result)
    assert effect.action == "code.execute"
    assert effect.effect == "code_executed"
    assert effect.status == "completed"


async def test_tool_search_returns_tools_discovered_effect() -> None:
    registry = ToolRegistry()
    registry.register(BashTool(), visibility=DEFERRED_VISIBILITY, keywords=["shell"])

    result = await ToolSearchTool(registry).execute({"query": "shell"})

    effect = _effect(result)
    assert effect.action == "tool.search"
    assert effect.effect == "tools_discovered"
    assert effect.details["activated_tools"] == ("bash",)


async def test_deep_research_returns_research_completed_effect() -> None:
    result = await DeepResearchTool(_FakeDeepResearch()).execute({"topic": "OpenBot"})

    effect = _effect(result)
    assert effect.action == "research.run"
    assert effect.effect == "research_completed"


async def test_load_skill_returns_skill_loaded_effect() -> None:
    result = await LoadSkillTool(_FakeSkillRegistry()).execute({"skill_name": "demo"})

    effect = _effect(result)
    assert effect.action == "skill.load"
    assert effect.effect == "skill_loaded"
    assert effect.target == "demo"


async def test_web_fetch_error_returns_failed_page_fetch_effect() -> None:
    result = await WebFetchTool().execute({"url": ""})

    effect = _effect(result)
    assert effect.action == "web.fetch"
    assert effect.status == "error"
    assert effect.effect == "none"


async def test_web_search_missing_key_returns_failed_search_effect(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    result = await WebSearchTool().execute({"query": "openbot"})

    effect = _effect(result)
    assert effect.action == "web.search"
    assert effect.status == "error"
    assert effect.effect == "none"


async def test_schedule_create_uses_context_target_and_returns_effect() -> None:
    scheduler = _FakeScheduler()
    tool = ScheduleManagerTool(lambda: scheduler)

    with tool_execution_context(
        ToolExecutionContext(conversation_id="8058699462", platform="telegram")
    ):
        result = await tool.execute(
            {
                "operation": "create",
                "name": "Daily review",
                "prompt": "Check the codebase",
                "cron": "0 8 * * *",
            }
        )

    effect = _effect(result)
    assert effect.action == "schedule.create"
    assert effect.effect == "schedule_created"
    assert effect.target == "sched-2"
