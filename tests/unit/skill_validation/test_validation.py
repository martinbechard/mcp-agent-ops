# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies copied Agent Skill validation through its structured service.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

from mcp_agent_ops.skill_validation.service import validate_skills


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
