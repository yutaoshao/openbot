"""Shared Pydantic validation helpers for built-in tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from src.tools.effects import EFFECT_NONE, STATUS_VALIDATION_ERROR, tool_effect
from src.tools.registry import ToolResult


class StrictToolInput(BaseModel):
    """Base class for tool inputs that reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


def schema_for(model: type[BaseModel]) -> dict[str, Any]:
    """Return the JSON schema exposed to model providers."""
    return model.model_json_schema()


def validate_args[InputModel: BaseModel](
    model: type[InputModel],
    args: dict[str, Any],
    *,
    tool_name: str,
) -> tuple[InputModel | None, ToolResult | None]:
    """Validate raw tool arguments and return a ToolResult on failure."""
    try:
        return model.model_validate(args), None
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_input=False)
        return None, ToolResult(
            content=f"Invalid arguments for {tool_name}: {len(errors)} validation error(s)",
            is_error=True,
            metadata={"validation_errors": errors},
            effects=(
                tool_effect(
                    f"{tool_name}.validate",
                    EFFECT_NONE,
                    status=STATUS_VALIDATION_ERROR,
                    name=tool_name,
                ),
            ),
        )
