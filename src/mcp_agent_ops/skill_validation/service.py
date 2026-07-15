# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Converts copied Agent Skill validation findings into a typed result.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

from pydantic import BaseModel, Field

from mcp_agent_ops.skill_validation.engine import validate_skill_paths


class SkillValidationFinding(BaseModel):
    """Describe one invalid Agent Skill path and validation message."""

    path: str
    message: str


class SkillValidationResult(BaseModel):
    """Return whether every requested Agent Skill passed copied validation."""

    ok: bool
    findings: list[SkillValidationFinding] = Field(default_factory=list)


def validate_skills(paths: list[Path]) -> SkillValidationResult:
    """Validate Agent Skill roots, directories, or exact manifests.

    Args:
        paths: Filesystem paths accepted by the copied skill validator.

    Returns:
        A typed result containing every validation finding. The operation is read-only.
    """
    findings = validate_skill_paths(paths)
    return SkillValidationResult(
        ok=not findings,
        findings=[SkillValidationFinding(path=str(finding.path), message=finding.message) for finding in findings],
    )
