"""Recovery rules for tool failures resolved within the same agent turn."""

from __future__ import annotations

from src.tools.effects import (
    EFFECT_NONE,
    STATUS_COMPLETED,
    STATUS_ERROR,
    STATUS_VALIDATION_ERROR,
    ToolEffect,
)

EFFECT_FILE_WRITTEN = "file_written"


def is_recovered_tool_problem(
    failed_effect: ToolEffect,
    later_effects: tuple[ToolEffect, ...],
) -> bool:
    """Return true when later tool evidence resolves an earlier failure."""
    if failed_effect.status == STATUS_VALIDATION_ERROR:
        return any(_same_tool_successful_retry(failed_effect, item) for item in later_effects)
    if _is_file_edit_failure(failed_effect):
        return any(_file_edit_success_matches(failed_effect, item) for item in later_effects)
    return False


def _same_tool_successful_retry(failed_effect: ToolEffect, later_effect: ToolEffect) -> bool:
    if later_effect.status != STATUS_COMPLETED:
        return False
    if failed_effect.name and later_effect.name != failed_effect.name:
        return False
    return later_effect.effect != EFFECT_NONE


def _is_file_edit_failure(effect: ToolEffect) -> bool:
    return (
        effect.action == "file.edit"
        and effect.name == "edit_file"
        and effect.status == STATUS_ERROR
        and effect.effect == EFFECT_NONE
        and bool(_effect_resource(effect))
    )


def _file_edit_success_matches(failed_effect: ToolEffect, later_effect: ToolEffect) -> bool:
    return (
        later_effect.action == "file.edit"
        and later_effect.name == "edit_file"
        and later_effect.status == STATUS_COMPLETED
        and later_effect.effect == EFFECT_FILE_WRITTEN
        and _effect_resource(later_effect) == _effect_resource(failed_effect)
    )


def _effect_resource(effect: ToolEffect) -> str:
    if effect.resource is not None:
        return effect.resource.canonical
    return effect.target
