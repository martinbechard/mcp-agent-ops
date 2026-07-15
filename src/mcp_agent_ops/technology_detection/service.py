# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Presents copied technology-skill detection as a structured domain service.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import argparse
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mcp_agent_ops.technology_detection.engine import detect


class TechnologyDetectionResult(BaseModel):
    """Return the copied detector exit code and structured loadout result."""

    exit_code: int
    result: dict[str, Any]


def detect_technology_skills(
    project_root: Path,
    scopes: list[str],
    registry: Path,
    skills_root: Path,
    available_skills: list[str] | None = None,
) -> TechnologyDetectionResult:
    """Detect technology skills for selected project scopes using copied rules.

    Args:
        project_root: Root of the project whose source evidence is inspected.
        scopes: Project-relative files or directories that need technology loadouts.
        registry: Explicit detection-registry YAML owned by the calling methodology.
        skills_root: Runtime skill root used for availability metadata.
        available_skills: Optional complete runtime catalog; when supplied it is the
            authority for skill availability across multiple roots.

    Returns:
        The detector's stable exit code and structured aggregate result. Detection is
        read-only and never writes to the inspected project or skill roots.
    """
    arguments = argparse.Namespace(
        project_root=project_root,
        scope=scopes,
        registry=registry,
        skills_root=skills_root,
        available_skill=available_skills,
    )
    result, exit_code = detect(arguments)
    return TechnologyDetectionResult(exit_code=exit_code, result=result)
