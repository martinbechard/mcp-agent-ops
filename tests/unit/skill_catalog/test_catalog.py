# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies skill discovery, precedence, content digests, and safe resource reads.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

import pytest

from mcp_agent_ops.skill_catalog.catalog import SkillCatalog, SkillResourceError
from mcp_agent_ops.skill_catalog.models import SkillResourceRequest


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

    published = catalog.public_result()
    assert published.skills[0].shadowed_count == 1
    assert "roots" not in published.model_dump()
    assert "path" not in published.skills[0].model_dump()
    assert "root" not in published.skills[0].model_dump()
    assert "shadowed_paths" not in published.skills[0].model_dump()


def test_catalog_recursively_discovers_nested_skills_in_selected_roots(tmp_path: Path) -> None:
    root = tmp_path / "project" / ".agents" / "skills"
    skill = write_skill(
        root,
        "backend/persistence/sql",
        "sql",
        "Project SQL skill.",
    )

    catalog = SkillCatalog.from_roots([root], recursive_roots=[root])

    assert catalog.get("sql").path == str((skill / "SKILL.md").resolve())


def test_catalog_rejects_duplicate_names_within_one_recursive_root(tmp_path: Path) -> None:
    root = tmp_path / "project" / ".agents" / "skills"
    write_skill(root, "backend/sql", "sql", "Backend SQL skill.")
    write_skill(root, "reporting/sql", "sql", "Reporting SQL skill.")

    with pytest.raises(ValueError, match="duplicate skill name 'sql'"):
        SkillCatalog.from_roots([root], recursive_roots=[root])


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


def test_catalog_keeps_skill_content_and_digest_in_one_immutable_snapshot(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = write_skill(root, "example", "example", "Example skill.", "# Example\n\nFirst version.\n")
    catalog = SkillCatalog.from_roots([root])
    original = catalog.read_skill("example")

    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example skill.\n---\n\n# Example\n\nSecond version.\n",
        encoding="utf-8",
    )

    unchanged = catalog.read_skill("example")
    refreshed = SkillCatalog.from_roots([root]).read_skill("example")
    assert unchanged.content == original.content
    assert unchanged.entry.digest == original.entry.digest
    assert refreshed.content.endswith("Second version.\n")
    assert refreshed.entry.digest != original.entry.digest


def test_catalog_lists_resources_beneath_hidden_install_roots(tmp_path: Path) -> None:
    root = tmp_path / ".codex" / "skills"
    skill = write_skill(root, "example", "example", "Installed example.")
    (skill / "detection.yaml").write_text("manifest: true\n", encoding="utf-8")

    entry = SkillCatalog.from_roots([root]).get("example")

    assert entry.resources == ["detection.yaml"]


def test_catalog_rejects_skill_links_outside_configured_roots(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    root.mkdir()
    external = write_skill(tmp_path / "external", "linked", "linked", "Linked skill.")
    (root / "linked").symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="outside configured skill roots"):
        SkillCatalog.from_roots([root])

    loaded = SkillCatalog.from_roots([root, external]).read_skill("linked")
    assert loaded.entry.name == "linked"


def test_batch_load_is_ordered_path_free_and_all_or_nothing(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    write_skill(root, "alpha", "alpha", "Alpha skill.", "# Alpha\n")
    write_skill(root, "beta", "beta", "Beta skill.", "# Beta\n")
    catalog = SkillCatalog.from_roots([root])

    loaded = catalog.load_skills(["beta", "alpha"])
    assert loaded.ok is True
    assert loaded.catalog_revision == catalog.result().revision
    assert [skill.name for skill in loaded.skills] == ["beta", "alpha"]
    assert loaded.skills[0].content.endswith("# Beta\n")
    assert "path" not in loaded.skills[0].model_dump()
    assert "root" not in loaded.skills[0].model_dump()

    missing = catalog.load_skills(["alpha", "missing"])
    assert missing.ok is False
    assert missing.skills == []
    assert missing.errors[0].code == "skill_not_found"
    duplicate = catalog.load_skills(["alpha", "alpha"])
    assert duplicate.ok is False
    assert duplicate.skills == []
    assert duplicate.errors[0].code == "duplicate_skill"


def test_batch_resource_load_preserves_order_and_never_returns_partial_content(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    alpha = write_skill(root, "alpha", "alpha", "Alpha skill.")
    beta = write_skill(root, "beta", "beta", "Beta skill.")
    (alpha / "guide.md").write_text("alpha guide\n", encoding="utf-8")
    (beta / "guide.md").write_text("beta guide\n", encoding="utf-8")
    catalog = SkillCatalog.from_roots([root])

    loaded = catalog.load_resources([
        SkillResourceRequest(skill_name="beta", resource_path="guide.md"),
        SkillResourceRequest(skill_name="alpha", resource_path="guide.md"),
    ])
    assert loaded.ok is True
    assert [resource.skill_name for resource in loaded.resources] == ["beta", "alpha"]
    assert [resource.content for resource in loaded.resources] == ["beta guide\n", "alpha guide\n"]

    missing = catalog.load_resources([
        SkillResourceRequest(skill_name="alpha", resource_path="guide.md"),
        SkillResourceRequest(skill_name="beta", resource_path="missing.md"),
    ])
    assert missing.ok is False
    assert missing.resources == []
    assert missing.errors[0].code == "resource_unavailable"


def test_catalog_requires_refresh_before_loading_a_new_resource(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    skill = write_skill(root, "example", "example", "Example skill.")
    catalog = SkillCatalog.from_roots([root])
    added = skill / "guide.md"
    added.write_text("published later\n", encoding="utf-8")

    with pytest.raises(SkillResourceError, match="not published in the catalog snapshot"):
        catalog.read_resource("example", "guide.md")

    refreshed = SkillCatalog.from_roots([root])
    loaded = refreshed.read_resource("example", "guide.md")
    assert loaded.content == "published later\n"
    assert len(loaded.digest) == 64


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
    with pytest.raises(SkillResourceError, match="must be relative"):
        catalog.read_resource("example", str(skill / "SKILL.md"))


def test_catalog_rejects_invalid_skill_frontmatter(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    invalid = root / "invalid"
    invalid.mkdir(parents=True)
    (invalid / "SKILL.md").write_text("# Missing frontmatter\n", encoding="utf-8")

    with pytest.raises(ValueError, match="YAML frontmatter"):
        SkillCatalog.from_roots([root])
