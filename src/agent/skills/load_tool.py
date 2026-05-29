"""Agent tool for loading skill instructions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.logging import get_logger
from src.tools.effects import EFFECT_NONE, STATUS_COMPLETED, STATUS_ERROR, tool_effect
from src.tools.registry import ToolResult

if TYPE_CHECKING:
    from src.agent.skills.registry import SkillRegistry

logger = get_logger(__name__)


class LoadSkillTool:
    """Load one skill's full SKILL.md instructions into context."""

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "load_skill"

    @property
    def description(self) -> str:
        return (
            "Loads one specialized skill's full SKILL.md instructions into context. "
            "Use when the current task matches an available skill listed in the system "
            "prompt and that skill's workflow would guide the answer or tool use. "
            "Do not use when a direct answer or visible tool is sufficient, or no listed "
            "skill clearly matches the task."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Name of the skill to load (from the available skills list)",
                },
            },
            "required": ["skill_name"],
        }

    @property
    def category(self) -> str:
        return "system"

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        skill_name = str(args.get("skill_name") or "")
        if not skill_name:
            return _result("skill_name is required", True, skill_name, STATUS_ERROR, EFFECT_NONE)

        content = self._registry.load(skill_name)
        if content is None:
            available = ", ".join(m.name for m in self._registry._skills.values())
            return _result(
                f"Skill '{skill_name}' not found. Available: {available}",
                True,
                skill_name,
                STATUS_ERROR,
                EFFECT_NONE,
            )

        refs = self._registry.list_references(skill_name)
        if refs:
            content += (
                "\n\n---\nAvailable reference files "
                "(use file_manager to read if needed):\n" + "\n".join(f"- {ref}" for ref in refs)
            )

        logger.info("skill.loaded", name=skill_name, length=len(content))
        return ToolResult(
            content=content,
            metadata={"references": refs},
            effects=(
                _effect(skill_name, STATUS_COMPLETED, "skill_loaded", references=tuple(refs)),
            ),
        )


def _result(content: str, is_error: bool, skill_name: str, status: str, effect: str) -> ToolResult:
    return ToolResult(
        content=content,
        is_error=is_error,
        effects=(_effect(skill_name, status, effect),),
    )


def _effect(skill_name: str, status: str, effect: str, **details: Any):
    return tool_effect(
        "skill.load",
        effect,
        status=status,
        target_type="skill",
        target=skill_name,
        name="load_skill",
        **details,
    )
