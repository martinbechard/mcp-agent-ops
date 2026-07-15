# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Enforces repository-root boundaries for verification inputs.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

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

