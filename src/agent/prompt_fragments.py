"""Dynamic prompt fragments for harness-level behavior guidance."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.task_state import TaskState

_ANALYSIS_FRAGMENT = """\
When investigating or debugging:
- State the concrete issue you are checking.
- Use evidence from tools before concluding.
- End with a structured summary of findings and next steps.
"""

_CODING_FRAGMENT = """\
When editing code:
- Prefer the smallest valid change set.
- Mention affected files and any verification you ran.
- If work is incomplete, say exactly what remains.
"""

_SCHEDULING_FRAGMENT = """\
When the user asks for future or recurring work:
- Prefer creating or updating a schedule/tool-based automation instead of only describing steps.
"""

_ACTIVE_TASK_FRAGMENT = """\
Keep the current task state aligned with your reply.
- Update progress incrementally.
- Avoid declaring completion unless the objective has concrete output or verified findings.
"""


def build_prompt_fragments(
    user_input: str,
    task_state: TaskState | None,
) -> list[str]:
    """Select prompt fragments based on the current task."""
    fragments = [_ACTIVE_TASK_FRAGMENT.strip()]
    lowered = user_input.lower()
    if any(token in lowered for token in ("debug", "investigate", "analyze", "分析", "排查")):
        fragments.append(_ANALYSIS_FRAGMENT.strip())
    if any(token in lowered for token in ("code", "fix", "implement", "refactor", "修改", "实现")):
        fragments.append(_CODING_FRAGMENT.strip())
    if any(token in lowered for token in ("schedule", "cron", "later", "定时", "提醒")):
        fragments.append(_SCHEDULING_FRAGMENT.strip())
    if task_state and task_state.activated_tools:
        fragments.append(
            "Only use activated deferred tools when they are relevant to the current objective."
        )
    return fragments
