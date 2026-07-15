# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies skill discovery, precedence, content digests, and safe resource reads.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

import pytest

from mcp_agent_ops.skill_catalog.catalog import SkillCatalog, SkillResourceError


def write_skill(root: Path, directory: str, name: str, description: str, body: str = "# Instructions\n") -> Path:
    """Create one complete test skill and return its directory."""
    skill = root / directory
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}",
        encoding="utf-8",
    )
    return skill


def test_catalog_uses_root_precedence_and_reports_shadowed_skills(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_skill = write_skill(first, "python", "python", "First Python skill.")
    second_skill = write_skill(second, "python", "python", "Second Python skill.")

    catalog = SkillCatalog.from_roots([first, second])
    entry = catalog.get("python")

    assert entry.description == "First Python skill."
    assert entry.path == str((first_skill / "SKILL.md").resolve())
    assert entry.shadowed_paths == [str((second_skill / "SKILL.md").resolve())]
    assert len(entry.digest) == 64


def test_catalog_reads_complete_skill_and_lists_supporting_resources(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = write_skill(root, "example", "example", "Example skill.", "# Example\n\nDo the work.\n")
    references = skill / "references"
    references.mkdir()
    (references / "guide.md").write_text("guide\n", encoding="utf-8")

    catalog = SkillCatalog.from_roots([root])
    loaded = catalog.read_skill("example")

    assert loaded.content.endswith("Do the work.\n")
    assert loaded.entry.resources == ["references/guide.md"]
    assert catalog.read_resource("example", "references/guide.md").content == "guide\n"


def test_catalog_rejects_resource_traversal_and_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = write_skill(root, "example", "example", "Example skill.")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (skill / "escape.txt").symlink_to(outside)
    catalog = SkillCatalog.from_roots([root])

    with pytest.raises(SkillResourceError, match="outside the skill directory"):
        catalog.read_resource("example", "../secret.txt")
    with pytest.raises(SkillResourceError, match="outside the skill directory"):
        catalog.read_resource("example", "escape.txt")


def test_catalog_rejects_invalid_skill_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    invalid = root / "invalid"
    invalid.mkdir(parents=True)
    (invalid / "SKILL.md").write_text("# Missing frontmatter\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML frontmatter"):
        SkillCatalog.from_roots([root])
