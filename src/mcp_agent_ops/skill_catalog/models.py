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

    revision: str
    roots: list[str]
    skills: list[SkillEntry]


class PublishedSkillEntry(BaseModel):
    """Describe one model-facing skill without exposing host filesystem paths."""

    name: str
    description: str
    digest: str
    resources: list[str] = Field(default_factory=list)
    shadowed_count: int = 0


class PublishedSkillCatalog(BaseModel):
    """Return the model-facing catalog revision and path-free skill metadata."""

    revision: str
    skills: list[PublishedSkillEntry]


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


class BatchLoadedSkill(BaseModel):
    """Return one model-facing skill document without exposing host filesystem paths."""

    name: str
    digest: str
    content: str
    resources: list[str] = Field(default_factory=list)


class SkillLoadError(BaseModel):
    """Describe one bounded batch-load rejection without returning partial skill content."""

    code: str
    message: str
    name: str | None = None


class SkillLoadResult(BaseModel):
    """Return an ordered all-or-nothing set of complete skill documents."""

    ok: bool
    catalog_revision: str
    skills: list[BatchLoadedSkill] = Field(default_factory=list)
    errors: list[SkillLoadError] = Field(default_factory=list)


class SkillResourceRequest(BaseModel):
    """Identify one supporting resource beneath a resolved skill package."""

    skill_name: str
    resource_path: str


class SkillResourceLoadError(BaseModel):
    """Describe one batch resource rejection without returning partial content."""

    code: str
    message: str
    skill_name: str | None = None
    resource_path: str | None = None


class SkillResourceLoadResult(BaseModel):
    """Return an ordered all-or-nothing set of supporting skill resources."""

    ok: bool
    catalog_revision: str
    resources: list[LoadedSkillResource] = Field(default_factory=list)
    errors: list[SkillResourceLoadError] = Field(default_factory=list)
