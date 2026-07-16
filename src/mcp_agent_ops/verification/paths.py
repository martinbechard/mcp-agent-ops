# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Enforces configured filesystem boundaries for MCP and verification inputs.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from collections.abc import Sequence
from pathlib import Path


class PathBoundaryError(ValueError):
    """Report that an input path or pattern can escape its configured root."""


def resolve_within_root(root: Path, value: str) -> Path:
    """Resolve one caller-supplied path without permitting root escape.

    Args:
        root: Trusted directory that owns all permitted paths.
        value: Absolute or root-relative path supplied by a caller.

    Returns:
        The normalized absolute path, which may refer to a missing future file.

    Raises:
        PathBoundaryError: If the value is empty or resolves outside `root`.

    This function performs no filesystem mutation.
    """
    resolved_root = root.resolve()
    if not value.strip():
        raise PathBoundaryError("Path cannot be empty.")
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (resolved_root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise PathBoundaryError(f"Path is outside the allowed root: {value}")
    return resolved


def resolve_within_roots(
    roots: Sequence[Path],
    value: str,
    boundary_name: str,
) -> Path:
    """Resolve one absolute caller path beneath administrator-configured roots.

    Args:
        roots: Trusted roots configured by the MCP host for one boundary type.
        value: Absolute path supplied by a model-facing MCP tool call.
        boundary_name: Short diagnostic label such as ``workspace`` or ``skill``.

    Returns:
        The normalized absolute path, including for a permitted future path.

    Raises:
        PathBoundaryError: If no roots are configured, the value is empty or relative,
            or its resolved location falls outside every configured root.

    This function performs no filesystem mutation and does not grant access merely because
    two paths share a textual prefix.
    """
    if not roots:
        raise PathBoundaryError(f"No configured {boundary_name} roots are available.")
    if not value.strip():
        raise PathBoundaryError("Path cannot be empty.")
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise PathBoundaryError(
            f"Path must be absolute within configured {boundary_name} roots: {value}"
        )
    resolved = candidate.resolve()
    resolved_roots = [root.expanduser().resolve() for root in roots]
    if not any(
        resolved == root or root in resolved.parents for root in resolved_roots
    ):
        raise PathBoundaryError(
            f"Path is outside configured {boundary_name} roots: {value}"
        )
    return resolved


def validate_glob_pattern(pattern: str) -> None:
    """Reject a glob pattern that can enumerate outside its owning root.

    Args:
        pattern: Root-relative glob expression.

    Raises:
        PathBoundaryError: If the pattern is empty, absolute, or contains a parent segment.
    """
    candidate = Path(pattern)
    if not pattern.strip() or candidate.is_absolute() or ".." in candidate.parts:
        raise PathBoundaryError(f"Pattern is outside the allowed root: {pattern}")
