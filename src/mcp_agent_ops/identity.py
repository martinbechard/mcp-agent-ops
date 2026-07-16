# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Computes a location-independent digest of installed MCP runtime resources.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from pathlib import Path


def runtime_identity() -> dict[str, object]:
    """Return the deterministic package version and installed runtime-content digest."""
    root = Path(__file__).resolve().parent
    files: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        if path.is_symlink():
            raise ValueError("Installed MCP runtime resources must not contain symlinks.")
        if not path.is_file():
            continue
        content = path.read_bytes()
        files.append({
            "path": relative.as_posix(),
            "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
    if not files:
        raise ValueError("Installed MCP runtime contains no identity-bearing resources.")
    encoded = json.dumps(
        files,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return {
        "schema": "mcp-agent-ops-runtime-identity",
        "schemaVersion": 1,
        "package": "mcp-agent-ops",
        "packageVersion": version("mcp-agent-ops"),
        "runtimeDigest": hashlib.sha256(encoded).hexdigest(),
        "fileCount": len(files),
    }
