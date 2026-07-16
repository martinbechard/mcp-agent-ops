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


def validate_skills(
    paths: list[Path],
    allowed_roots: list[Path] | None = None,
) -> SkillValidationResult:
    """Validate Agent Skill roots, directories, or exact manifests.

    Args:
        paths: Filesystem paths accepted by the copied skill validator.
        allowed_roots: Optional trusted roots that every discovered manifest and metadata
            file must remain beneath after symlink resolution.

    Returns:
        A typed result containing every validation finding. The operation is read-only.
    """
    findings = validate_skill_paths(paths, allowed_roots)
    return SkillValidationResult(
        ok=not findings,
        findings=[
            SkillValidationFinding(
                path=_display_path(finding.path, allowed_roots),
                message=finding.message,
            )
            for finding in findings
        ],
    )


def _display_path(path: Path, allowed_roots: list[Path] | None) -> str:
    """Return a path-free diagnostic identity when validation is root-confined."""
    if allowed_roots is None:
        return str(path)
    absolute = path.expanduser().absolute()
    for root in allowed_roots:
        try:
            return absolute.relative_to(root.expanduser().absolute()).as_posix()
        except ValueError:
            continue
    return path.name
