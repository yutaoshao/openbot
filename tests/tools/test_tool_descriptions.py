from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.skills import LoadSkillTool, SkillRegistry
from src.tools.builtin import (
    BashTool,
    CodeExecutorTool,
    DeepResearchTool,
    EditFileTool,
    FileManagerTool,
    GlobTool,
    GrepTool,
    ScheduleManagerTool,
    ToolSearchTool,
    WebFetchTool,
    WebSearchTool,
)
from src.tools.builtin.file_mutation_tools import AppendFileTool, CreateFileTool, ReplaceFileTool
from src.tools.file_mutation_service import FileMutationService
from src.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from pathlib import Path

DESCRIPTION_PHRASES = ("Use when", "Do not use when")


def test_builtin_tool_descriptions_use_three_part_contract(tmp_path: Path) -> None:
    registry = ToolRegistry()
    mutation_service = FileMutationService(tmp_path)
    tools = [
        ToolSearchTool(registry),
        WebSearchTool(),
        WebFetchTool(),
        CodeExecutorTool(),
        FileManagerTool(root=tmp_path),
        CreateFileTool(mutation_service),
        AppendFileTool(mutation_service),
        EditFileTool(mutation_service),
        ReplaceFileTool(mutation_service),
        BashTool(root=tmp_path),
        GlobTool(root=tmp_path),
        GrepTool(root=tmp_path),
        ScheduleManagerTool(lambda: None),
        DeepResearchTool(object()),
        LoadSkillTool(SkillRegistry(skills_dirs=[tmp_path])),
    ]

    for tool in tools:
        description = tool.description
        assert not description.startswith("Purpose:"), tool.name
        assert [description.find(phrase) for phrase in DESCRIPTION_PHRASES] == sorted(
            description.find(phrase) for phrase in DESCRIPTION_PHRASES
        ), tool.name
        for phrase in DESCRIPTION_PHRASES:
            assert phrase in description, tool.name
