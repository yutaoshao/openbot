"""Tests for the skill system."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.agent.skills import LoadSkillTool, SkillRegistry

if TYPE_CHECKING:
    from pathlib import Path


def _create_skill(tmp_path: Path, name: str, description: str, body: str = "") -> Path:
    """Helper to create a skill directory with SKILL.md."""
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n"
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content)
    return skill_dir


class TestSkillRegistry:
    def test_discovers_skills(self, tmp_path: Path) -> None:
        _create_skill(tmp_path, "research", "Use when doing research")
        _create_skill(tmp_path, "translate", "Use when translating")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        skills = registry.list_skills()

        assert len(skills) == 2
        names = {s["name"] for s in skills}
        assert names == {"research", "translate"}

    def test_empty_dir(self, tmp_path: Path) -> None:
        registry = SkillRegistry(skills_dirs=[tmp_path])
        assert registry.list_skills() == []
        assert registry.get_metadata_prompt() == ""

    def test_nonexistent_dir(self) -> None:
        registry = SkillRegistry(skills_dirs=["/nonexistent/path"])
        assert registry.list_skills() == []

    def test_metadata_prompt(self, tmp_path: Path) -> None:
        _create_skill(tmp_path, "research", "Use when doing research")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        prompt = registry.get_metadata_prompt()

        assert "Available skills" in prompt
        assert "research" in prompt
        assert "Use when doing research" in prompt

    def test_load_skill(self, tmp_path: Path) -> None:
        _create_skill(
            tmp_path, "test-skill", "Use when testing",
            body="# Instructions\nDo something.",
        )

        registry = SkillRegistry(skills_dirs=[tmp_path])
        content = registry.load("test-skill")

        assert content is not None
        assert "# Instructions" in content
        assert "Do something." in content

    def test_load_nonexistent(self, tmp_path: Path) -> None:
        registry = SkillRegistry(skills_dirs=[tmp_path])
        assert registry.load("nonexistent") is None

    def test_missing_frontmatter(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# No frontmatter here\nJust text.")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        assert registry.list_skills() == []

    def test_missing_name_field(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "no-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: Something\n---\n\nBody.")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        assert registry.list_skills() == []

    def test_references_listing(self, tmp_path: Path) -> None:
        skill_dir = _create_skill(tmp_path, "with-refs", "Use for refs")
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "guide.md").write_text("# Guide")
        (refs_dir / "api.md").write_text("# API")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        refs = registry.list_references("with-refs")

        assert len(refs) == 2
        assert "references/api.md" in refs
        assert "references/guide.md" in refs

    def test_get_reference(self, tmp_path: Path) -> None:
        skill_dir = _create_skill(tmp_path, "ref-skill", "Use for ref test")
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "doc.md").write_text("Reference content here")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        content = registry.get_reference("ref-skill", "references/doc.md")

        assert content == "Reference content here"

    def test_get_reference_path_traversal(self, tmp_path: Path) -> None:
        _create_skill(tmp_path, "safe", "Use safely")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        result = registry.get_reference("safe", "../../etc/passwd")

        assert result is None

    def test_reload(self, tmp_path: Path) -> None:
        registry = SkillRegistry(skills_dirs=[tmp_path])
        assert len(registry.list_skills()) == 0

        _create_skill(tmp_path, "new-skill", "Use for new things")
        registry.reload()

        assert len(registry.list_skills()) == 1

    def test_multi_dir_discovery(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "global"
        dir_b = tmp_path / "project"
        dir_a.mkdir()
        dir_b.mkdir()
        _create_skill(dir_a, "skill-a", "From global")
        _create_skill(dir_b, "skill-b", "From project")

        registry = SkillRegistry(skills_dirs=[dir_a, dir_b])
        names = {s["name"] for s in registry.list_skills()}
        assert names == {"skill-a", "skill-b"}

    def test_multi_dir_override(self, tmp_path: Path) -> None:
        """Higher-priority dir (later) overrides lower-priority (earlier)."""
        dir_low = tmp_path / "low"
        dir_high = tmp_path / "high"
        dir_low.mkdir()
        dir_high.mkdir()
        _create_skill(dir_low, "shared", "Low priority version", body="LOW")
        _create_skill(dir_high, "shared", "High priority version", body="HIGH")

        registry = SkillRegistry(skills_dirs=[dir_low, dir_high])
        skills = registry.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "shared"

        content = registry.load("shared")
        assert content is not None
        assert "HIGH" in content
        assert "Low" not in content

    def test_nonexistent_dirs_skipped(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        _create_skill(real_dir, "test", "Use when testing")

        registry = SkillRegistry(skills_dirs=[
            tmp_path / "nope1",
            tmp_path / "nope2",
            real_dir,
        ])
        assert len(registry.list_skills()) == 1


class TestLoadSkillTool:
    async def test_load_existing(self, tmp_path: Path) -> None:
        _create_skill(tmp_path, "test", "Use when testing", body="# Test instructions")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        tool = LoadSkillTool(registry)
        result = await tool.execute({"skill_name": "test"})

        assert not result.is_error
        assert "# Test instructions" in result.content

    async def test_load_nonexistent(self, tmp_path: Path) -> None:
        registry = SkillRegistry(skills_dirs=[tmp_path])
        tool = LoadSkillTool(registry)
        result = await tool.execute({"skill_name": "nope"})

        assert result.is_error
        assert "not found" in result.content

    async def test_load_empty_name(self, tmp_path: Path) -> None:
        registry = SkillRegistry(skills_dirs=[tmp_path])
        tool = LoadSkillTool(registry)
        result = await tool.execute({"skill_name": ""})

        assert result.is_error

    async def test_includes_references(self, tmp_path: Path) -> None:
        skill_dir = _create_skill(tmp_path, "with-refs", "Use for refs", body="Body")
        refs_dir = skill_dir / "references"
        refs_dir.mkdir()
        (refs_dir / "extra.md").write_text("Extra info")

        registry = SkillRegistry(skills_dirs=[tmp_path])
        tool = LoadSkillTool(registry)
        result = await tool.execute({"skill_name": "with-refs"})

        assert not result.is_error
        assert "references/extra.md" in result.content
