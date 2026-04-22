"""Skill system — progressive disclosure of domain-specific knowledge.

Implements the industry-standard 3-layer loading mechanism:

1. **Match** — All skill metadata (name + description) is injected into the
   system prompt so the Agent can identify relevant skills.
2. **Read** — When a skill matches, the Agent calls ``load_skill`` to read
   the full SKILL.md instructions into context.
3. **Execute** — The Agent follows the instructions, optionally reading
   files from ``references/`` or running ``scripts/``.

Skill directory structure::

    data/skills/<skill-name>/
    ├── SKILL.md          # Required: YAML frontmatter + instructions
    ├── scripts/          # Optional: executable code
    ├── references/       # Optional: reference docs (loaded on demand)
    └── assets/           # Optional: templates, files for output

SKILL.md frontmatter (required fields)::

    ---
    name: skill-name
    description: Use when [triggering conditions]...
    ---
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.logging import get_logger
from src.tools.registry import ToolResult

logger = get_logger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.+?)\n---\s*\n", re.DOTALL)
_FIELD_RE = re.compile(r"^(\w+):\s*(.+)$", re.MULTILINE)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SkillMeta:
    """Parsed metadata from a SKILL.md frontmatter."""

    name: str
    description: str
    path: Path  # path to SKILL.md

    @property
    def dir(self) -> Path:
        """Skill root directory (parent of SKILL.md)."""
        return self.path.parent


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Discovers and manages skills from multiple filesystem locations.

    Scans skill directories in priority order (lowest first), so that
    project-level skills override global ones when names collide.

    Default scan order (lowest → highest priority):
    1. ``~/.claude/skills/``       — user global
    2. ``.claude/skills/``         — project-level (Claude Code convention)
    3. ``.agents/skills/``         — project-level (generic agent convention)
    4. ``data/skills/``            — project built-in skills

    Provides:
    - ``get_metadata_prompt()`` — one-liner summaries for system prompt
    - ``load(name)`` — full SKILL.md content for the Agent
    - ``list_references(name)`` — files in ``references/``
    """

    def __init__(
        self,
        skills_dirs: list[str | Path] | None = None,
    ) -> None:
        if skills_dirs is not None:
            self._dirs = [Path(d) for d in skills_dirs]
        else:
            self._dirs = self._default_dirs()
        self._skills: dict[str, SkillMeta] = {}
        self._scan()

    @staticmethod
    def _default_dirs() -> list[Path]:
        """Return default skill directories in priority order (low → high)."""
        home = Path.home()
        return [
            home / ".claude" / "skills",  # user global
            Path(".claude") / "skills",  # project Claude Code
            Path(".agents") / "skills",  # project generic
            Path("data") / "skills",  # project built-in
        ]

    def _scan(self) -> None:
        """Scan all skill directories and parse SKILL.md frontmatters.

        Scanned in order: later directories override earlier ones
        when skill names collide (higher priority wins).
        """
        self._skills.clear()

        for skills_dir in self._dirs:
            if not skills_dir.is_dir():
                continue
            for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
                meta = self._parse_frontmatter(skill_md)
                if meta:
                    if meta.name in self._skills:
                        logger.debug(
                            "skill.override",
                            name=meta.name,
                            old_path=str(self._skills[meta.name].path),
                            new_path=str(skill_md),
                        )
                    self._skills[meta.name] = meta
                    logger.debug(
                        "skill.discovered",
                        name=meta.name,
                        source=str(skills_dir),
                    )

        logger.info("skill.scan_complete", count=len(self._skills))

    @staticmethod
    def _parse_frontmatter(path: Path) -> SkillMeta | None:
        """Extract name and description from SKILL.md YAML frontmatter."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        m = _FRONTMATTER_RE.match(text)
        if not m:
            logger.warning("skill.no_frontmatter", path=str(path))
            return None

        fields: dict[str, str] = {}
        for fm in _FIELD_RE.finditer(m.group(1)):
            fields[fm.group(1).strip()] = fm.group(2).strip()

        name = fields.get("name", "")
        description = fields.get("description", "")
        if not name or not description:
            logger.warning(
                "skill.missing_fields",
                path=str(path),
                has_name=bool(name),
                has_desc=bool(description),
            )
            return None

        return SkillMeta(name=name, description=description, path=path)

    # -- Public API --------------------------------------------------------

    def get_metadata_prompt(self) -> str:
        """Build the skill metadata block for injection into system prompt.

        Returns a short text listing all available skills with their
        triggering descriptions.  This is Layer 1 of progressive disclosure.
        """
        if not self._skills:
            return ""

        lines = ["Available skills (call load_skill to activate):"]
        for meta in self._skills.values():
            lines.append(f"- {meta.name}: {meta.description}")
        return "\n".join(lines)

    def load(self, name: str) -> str | None:
        """Load the full SKILL.md content for a given skill name.

        This is Layer 2 of progressive disclosure.
        Returns None if the skill is not found.
        """
        meta = self._skills.get(name)
        if not meta:
            return None
        try:
            return meta.path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("skill.read_error", name=name, path=str(meta.path))
            return None

    def list_references(self, name: str) -> list[str]:
        """List available reference files for a skill (Layer 3)."""
        meta = self._skills.get(name)
        if not meta:
            return []
        refs_dir = meta.dir / "references"
        if not refs_dir.is_dir():
            return []
        return [str(f.relative_to(meta.dir)) for f in sorted(refs_dir.iterdir()) if f.is_file()]

    def get_reference(self, name: str, ref_path: str) -> str | None:
        """Read a specific reference file from a skill's references/ dir."""
        meta = self._skills.get(name)
        if not meta:
            return None
        target = (meta.dir / ref_path).resolve()
        # Prevent path traversal
        if not str(target).startswith(str(meta.dir.resolve())):
            return None
        if not target.is_file():
            return None
        try:
            return target.read_text(encoding="utf-8")
        except OSError:
            return None

    def list_skills(self) -> list[dict[str, str]]:
        """Return all skill metadata as a list of dicts (for API)."""
        return [
            {"name": m.name, "description": m.description, "path": str(m.path)}
            for m in self._skills.values()
        ]

    def reload(self) -> None:
        """Re-scan the skills directory (e.g. after adding a new skill)."""
        self._scan()


# ---------------------------------------------------------------------------
# Tool: load_skill
# ---------------------------------------------------------------------------


class LoadSkillTool:
    """Agent tool for loading a skill's full instructions.

    The Agent calls this when it determines a user's task matches
    an available skill (based on metadata in the system prompt).
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "load_skill"

    @property
    def description(self) -> str:
        return (
            "Load a specialized skill's full instructions into context. "
            "Call this when the current task matches an available skill "
            "listed in the system prompt. The skill will provide detailed "
            "workflow guidance for the task."
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
        skill_name = args.get("skill_name", "")
        if not skill_name:
            return ToolResult(content="skill_name is required", is_error=True)

        content = self._registry.load(skill_name)
        if content is None:
            available = ", ".join(m.name for m in self._registry._skills.values())
            return ToolResult(
                content=f"Skill '{skill_name}' not found. Available: {available}",
                is_error=True,
            )

        # Include reference file listing if any exist
        refs = self._registry.list_references(skill_name)
        if refs:
            content += (
                "\n\n---\nAvailable reference files "
                "(use file_manager to read if needed):\n" + "\n".join(f"- {r}" for r in refs)
            )

        logger.info("skill.loaded", name=skill_name, length=len(content))
        return ToolResult(
            content=content,
            metadata={"skill_name": skill_name, "references": refs},
        )
