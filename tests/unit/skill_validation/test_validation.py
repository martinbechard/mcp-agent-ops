# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies copied Agent Skill validation through its structured service.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

import pytest
from pytest import MonkeyPatch

from mcp_agent_ops.skill_validation.service import validate_skills


def test_validate_skills_rejects_an_empty_path_list() -> None:
    with pytest.raises(ValueError, match="At least one skill validation path is required"):
        validate_skills([])


def test_validate_skills_returns_structured_findings(tmp_path: Path) -> None:
    skill = tmp_path / "WrongDirectory"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: invalid_name\ndescription: Invalid <description>.\nunexpected: true\n---\n",
        encoding="utf-8",
    )

    result = validate_skills([skill])

    assert result.ok is False
    assert {finding.message for finding in result.findings} >= {
        "unexpected frontmatter keys: unexpected",
        "frontmatter name must use lowercase letters, digits, and hyphens",
        "frontmatter description must not contain angle brackets",
    }


def test_validate_skills_accepts_a_minimal_valid_skill(tmp_path: Path) -> None:
    skill = tmp_path / "valid-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: valid-skill\ndescription: A valid skill.\n---\n\n# Valid Skill\n",
        encoding="utf-8",
    )

    result = validate_skills([skill])

    assert result.ok is True
    assert result.findings == []


def test_validate_skills_never_reads_a_manifest_outside_allowed_roots(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    external_manifest = external / "SKILL.md"
    external_manifest.write_text(
        "---\nname: linked\ndescription: External skill.\n---\n",
        encoding="utf-8",
    )
    (allowed / "linked").symlink_to(external, target_is_directory=True)
    original = Path.read_text

    def guarded_read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        if path.resolve() == external_manifest.resolve():
            raise AssertionError("external skill manifest was read")
        return original(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    result = validate_skills([allowed], allowed_roots=[allowed])

    assert result.ok is False
    assert result.findings[0].path == "linked/SKILL.md"
    assert result.findings[0].message == "path resolves outside configured skill roots"


def test_validate_skills_rechecks_manifest_and_metadata_symlinks(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    skill = allowed / "example"
    skill.mkdir(parents=True)
    external_manifest = tmp_path / "external-SKILL.md"
    external_manifest.write_text(
        "---\nname: example\ndescription: External manifest.\n---\n",
        encoding="utf-8",
    )
    (skill / "SKILL.md").symlink_to(external_manifest)

    manifest_result = validate_skills([skill], allowed_roots=[allowed])
    assert manifest_result.ok is False
    assert manifest_result.findings[0].message == "path resolves outside configured skill roots"

    (skill / "SKILL.md").unlink()
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Valid skill.\n---\n",
        encoding="utf-8",
    )
    metadata_directory = skill / "agents"
    metadata_directory.mkdir()
    external_metadata = tmp_path / "external-openai.yaml"
    external_metadata.write_text("policy: {}\n", encoding="utf-8")
    (metadata_directory / "openai.yaml").symlink_to(external_metadata)

    metadata_result = validate_skills([skill], allowed_roots=[allowed])
    assert metadata_result.ok is False
    assert metadata_result.findings[0].path == "example/agents/openai.yaml"
    assert metadata_result.findings[0].message == "path resolves outside configured skill roots"


def test_validate_skills_allows_links_into_an_explicit_second_root(tmp_path: Path) -> None:
    first = tmp_path / "first"
    first.mkdir()
    second_skill = tmp_path / "second" / "linked"
    second_skill.mkdir(parents=True)
    (second_skill / "SKILL.md").write_text(
        "---\nname: linked\ndescription: Allowed linked skill.\n---\n",
        encoding="utf-8",
    )
    (first / "linked").symlink_to(second_skill, target_is_directory=True)

    result = validate_skills(
        [first],
        allowed_roots=[first, second_skill],
    )

    assert result.ok is True
    assert result.findings == []
