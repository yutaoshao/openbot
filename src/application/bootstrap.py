"""Runtime bootstrap helpers for the application container."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.agent.coordination import UserExecutionCoordinator
from src.agent.delegation import SubAgent
from src.agent.research import DeepResearch
from src.agent.skills import LoadSkillTool, SkillRegistry
from src.channels.adapters.web import WebAdapter
from src.channels.hub import MsgHub
from src.core.monitor import MetricsCollector
from src.infrastructure.embedding import EmbeddingService, NullEmbeddingService
from src.infrastructure.reranker import NullRerankerService, RerankerService
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


def init_runtime_services(app: Any) -> None:
    """Attach the runtime-only services owned by Application."""
    app.embedding_service = (
        EmbeddingService(app.config.embedding)
        if app.config.embedding.enabled
        else NullEmbeddingService()
    )
    app.reranker_service = (
        RerankerService(app.config.reranker)
        if app.config.reranker.enabled
        else NullRerankerService()
    )
    app.deep_research = DeepResearch(
        model_gateway=app.model_gateway,
        event_bus=app.event_bus,
    )
    app.skill_registry = SkillRegistry()
    app.msg_hub = MsgHub(app.event_bus)
    app.telegram = None
    app.feishu = None
    app.wechat = None
    app.web_adapter = WebAdapter()
    app.scheduler = None
    app.monitor = MetricsCollector(app.storage, app.event_bus)
    app.api_server = None
    app.api_app = None
    app.api_task = None
    app.housekeeping_task = None
    app.execution_coordinator = UserExecutionCoordinator()
    app.sub_agent = SubAgent(
        model_gateway=app.model_gateway,
        event_bus=app.event_bus,
        config=app.config.agent,
        tool_registry=app.tool_registry,
    )
    app.msg_hub.register_adapter("web", app.web_adapter)


def register_builtin_tools(app: Any) -> None:
    """Register all built-in tools."""
    file_mutations = FileMutationService(Path("."))
    app.tool_registry.register(
        ToolSearchTool(app.tool_registry),
        visibility=CORE_VISIBILITY,
    )
    app.tool_registry.register(
        WebSearchTool(),
        visibility=CORE_VISIBILITY,
        keywords=["search", "news", "最新", "查一下"],
    )
    app.tool_registry.register(
        WebFetchTool(),
        visibility=CORE_VISIBILITY,
        keywords=["read url", "fetch page", "网页", "文档"],
    )
    app.tool_registry.register(
        CodeExecutorTool(),
        visibility=CORE_VISIBILITY,
        keywords=["run code", "python", "calculate", "计算"],
    )
    app.tool_registry.register(
        FileManagerTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["file", "workspace", "read file", "文件"],
    )
    app.tool_registry.register(
        CreateFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["create file", "new file", "新建文件"],
    )
    app.tool_registry.register(
        AppendFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["append file", "add notes", "追加", "补充笔记"],
    )
    app.tool_registry.register(
        EditFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["edit file", "replace text", "patch", "修改文件", "增量编辑"],
    )
    app.tool_registry.register(
        ReplaceFileTool(file_mutations),
        visibility=CORE_VISIBILITY,
        keywords=["replace file", "rewrite file", "完整替换", "重写文件"],
    )
    app.tool_registry.register(
        BashTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["bash", "shell", "terminal", "git", "pytest", "终端", "命令"],
    )
    app.tool_registry.register(
        GlobTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["glob", "find file", "list files", "文件搜索"],
    )
    app.tool_registry.register(
        GrepTool(root=Path(".")),
        visibility=CORE_VISIBILITY,
        keywords=["grep", "ripgrep", "search code", "内容搜索", "搜索代码"],
    )
    app.tool_registry.register(
        ScheduleManagerTool(lambda: app.scheduler),
        visibility=CORE_VISIBILITY,
        keywords=["schedule", "cron", "later", "提醒", "定时"],
    )
    app.tool_registry.register(
        DeepResearchTool(app.deep_research),
        visibility=DEFERRED_VISIBILITY,
        keywords=["deep research", "investigate deeply", "调研", "深度研究"],
    )
    app.tool_registry.register(
        LoadSkillTool(app.skill_registry),
        visibility=DEFERRED_VISIBILITY,
        keywords=["skill", "workflow", "规范", "技能"],
    )
