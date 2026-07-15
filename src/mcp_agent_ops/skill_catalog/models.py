# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Defines structured skill catalog, complete skill, and supporting resource results.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pydantic import BaseModel, Field


class SkillEntry(BaseModel):
    """Describe one precedence-resolved installed Agent Skill.

    `path` identifies the complete `SKILL.md`, `digest` identifies its immutable
    bytes, and `shadowed_paths` exposes lower-precedence definitions with the same name.
    """

    name: str
    description: str
    path: str
    root: str
    digest: str
    resources: list[str] = Field(default_factory=list)
    shadowed_paths: list[str] = Field(default_factory=list)


class SkillCatalogResult(BaseModel):
    """Return the configured roots and all precedence-resolved skill entries."""

    roots: list[str]
    skills: list[SkillEntry]


class LoadedSkill(BaseModel):
    """Return one complete skill document together with its catalog metadata."""

    entry: SkillEntry
    content: str


class LoadedSkillResource(BaseModel):
    """Return one safely resolved supporting resource in text or base64 form."""

    skill_name: str
    path: str
    mime_type: str
    digest: str
    content: str | None = None
    data_base64: str | None = None

