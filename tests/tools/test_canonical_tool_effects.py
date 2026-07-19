from __future__ import annotations

from typing import TYPE_CHECKING

from src.tools.builtin.bash_tool import BashTool
from src.tools.builtin.code_executor import CodeExecutorTool
from src.tools.builtin.deep_research import DeepResearchTool
from src.tools.builtin.edit_file import EditFileTool
from src.tools.builtin.file_mutation_tools import AppendFileTool
from src.tools.builtin.glob_tool import GlobTool
from src.tools.builtin.grep_tool import GrepTool
from src.tools.builtin.schedule_manager import ScheduleManagerTool
from src.tools.builtin.tool_search import ToolSearchTool
from src.tools.builtin.web_fetch import WebFetchTool
from src.tools.builtin.web_search import WebSearchTool
from src.tools.file_mutation_service import FileMutationService
from src.tools.registry import DEFERRED_VISIBILITY, ToolRegistry

if TYPE_CHECKING:
    from pathlib import Path


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


class _FakeScheduler:
    timezone_name = "Asia/Shanghai"

    async def create_schedule(self, **fields):
        return {"id": "sched-1", "next_run_at": None, **fields}

    async def list_schedules(self, **_):
        return [{"id": "sched-1", "name": "Daily", "status": "active", "cron": "0 8 * * *"}]


def _resource(effect):
    assert effect.resource is not None
    return effect.resource


async def test_file_tools_emit_same_canonical_resource_for_same_file(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    target = tmp_path / "notes" / "example.md"
    target.write_text("old\n", encoding="utf-8")

    mutation_service = FileMutationService(tmp_path)
    edit_result = await EditFileTool(mutation_service).execute(
        {"file_path": "./notes/example.md", "old_text": "old", "new_text": "new"}
    )
    append_result = await AppendFileTool(mutation_service).execute(
        {"path": "notes/../notes/example.md", "content": "next\n"}
    )

    assert _resource(edit_result.effects[0]).canonical == "notes/example.md"
    assert _resource(append_result.effects[0]).canonical == "notes/example.md"
    assert edit_result.effects[0].target == "notes/example.md"
    assert append_result.effects[0].target == "notes/example.md"


async def test_builtin_tools_emit_canonical_resource_schema(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(BashTool(), visibility=DEFERRED_VISIBILITY, keywords=["shell"])
    scheduler = _FakeScheduler()
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    results = [
        await GrepTool(root=tmp_path).execute({"pattern": "hello", "path": "./src"}),
        await GlobTool(root=tmp_path).execute({"pattern": "*.py", "path": "./src"}),
        await WebFetchTool().execute({"url": ""}),
        await WebSearchTool().execute({"query": "openbot"}),
        await DeepResearchTool(_FakeDeepResearch()).execute({"topic": "OpenBot"}),
        await BashTool(root=tmp_path).execute({"description": "print", "command": "printf hi"}),
        await CodeExecutorTool().execute({"code": "print('hi')"}),
        await ScheduleManagerTool(lambda: scheduler).execute({"operation": "list"}),
        await ToolSearchTool(registry).execute({"query": "shell"}),
    ]

    resources = [_resource(item.effects[0]) for item in results]

    assert [resource.kind for resource in resources] == [
        "file",
        "file",
        "url",
        "query",
        "topic",
        "command",
        "command",
        "schedule",
        "tool",
    ]
    assert resources[0].canonical == "src"
    assert resources[1].canonical == "src"
