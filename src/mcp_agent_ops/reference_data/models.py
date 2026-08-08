# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Defines path-free reference catalog and aggregated load results.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pydantic import BaseModel, Field


class ReferenceSourceMetadata(BaseModel):
    """Identify one aggregated scope's immutable bytes without exposing its host path."""

    scope: str
    digest: str
    byte_count: int


class AggregatedReference(BaseModel):
    """Return one named reference assembled from every matching scope in search order."""

    name: str
    digest: str
    content: str
    source_count: int
    sources: list[ReferenceSourceMetadata]


class PublishedReferenceCatalog(BaseModel):
    """Describe the active path-free reference snapshot and its available names."""

    revision: str
    names: list[str] = Field(default_factory=list)


class ReferenceLoadError(BaseModel):
    """Describe one bounded reference-load rejection without returning partial content."""

    code: str
    message: str
    name: str | None = None


class ReferenceLoadResult(BaseModel):
    """Return ordered aggregated references or an error-only all-or-nothing result."""

    ok: bool
    catalog_revision: str
    references: list[AggregatedReference] = Field(default_factory=list)
    errors: list[ReferenceLoadError] = Field(default_factory=list)
