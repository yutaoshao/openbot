"""Runtime bootstrap helpers for the application container."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.agent.skills import LoadSkillTool
from src.tools.builtin import (
    AppendFileTool,
    BashTool,
    CodeExecutorTool,
    CreateFileTool,
    DeepResearchTool,
    EditFileTool,
    FileManagerTool,
    GlobTool,
    GrepTool,
    ReplaceFileTool,
    ScheduleManagerTool,
    ToolSearchTool,
    WebFetchTool,
    WebSearchTool,
)
from src.tools.file_mutation_service import FileMutationService
from src.tools.registry import CORE_VISIBILITY, DEFERRED_VISIBILITY

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.agent.research import DeepResearch
    from src.agent.scheduling import AgentScheduler
    from src.agent.skills import SkillRegistry
    from src.tools.registry import ToolRegistry


def register_builtin_tools(
    registry: ToolRegistry,
    deep_research: DeepResearch,
    skill_registry: SkillRegistry,
    scheduler_provider: Callable[[], AgentScheduler | None],
) -> None:
    """Register all built-in tools."""
    file_mutations = FileMutationService(Path("."))
    registry.register(
        ToolSearchTool(registry),
        visibility=CORE_VISIBILITY,
    )
    registry.register(
        WebSearchTool(),
        visibility=CORE_VISIBILITY,
        keywords=["search", "news", "最新", "查一下"],
    )
    registry.register(
        WebFetchTool(),
        visibility=CORE_VISIBILITY,
        keywords=["read url", "fetch page", "网页", "文档"],
    )
    registry.register(
        CodeExecutorTool(),
        visibility=CORE_VISIBILITY,
        keywords=["run code", "python", "calculate", "计算"],
    )
    registry.register(
        FileManagerTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["file", "workspace", "read file", "文件"],
    )
    registry.register(
        CreateFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["create file", "new file", "新建文件"],
    )
    registry.register(
        AppendFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["append file", "add notes", "追加", "补充笔记"],
    )
    registry.register(
        EditFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["edit file", "replace text", "patch", "修改文件", "增量编辑"],
    )
    registry.register(
        ReplaceFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["replace file", "rewrite file", "完整替换", "重写文件"],
    )
    registry.register(
        BashTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["bash", "shell", "terminal", "git", "pytest", "终端", "命令"],
    )
    registry.register(
        GlobTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["glob", "find file", "list files", "文件搜索"],
    )
    registry.register(
        GrepTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["grep", "ripgrep", "search code", "内容搜索", "搜索代码"],
    )
    registry.register(
        ScheduleManagerTool(scheduler_provider),
        visibility=CORE_VISIBILITY,
        keywords=["schedule", "cron", "later", "提醒", "定时"],
    )
    registry.register(
        DeepResearchTool(deep_research),
        visibility=DEFERRED_VISIBILITY,
        keywords=["deep research", "investigate deeply", "调研", "深度研究"],
    )
    registry.register(
        LoadSkillTool(skill_registry),
        visibility=DEFERRED_VISIBILITY,
        keywords=["skill", "workflow", "规范", "技能"],
    )
