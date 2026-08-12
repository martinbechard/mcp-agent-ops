# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Converts package-owned claim-engine commands into structured in-process adapter results.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from mcp_agent_ops.claims import engine


class ClaimCommandResult(BaseModel):
    """Return one package claim-engine exit code and structured JSON result."""

    exit_code: int
    result: dict[str, Any]


def run_claim_command(arguments: Sequence[str]) -> ClaimCommandResult:
    """Execute the package-owned claim engine through its structured dispatch boundary.

    Args:
        arguments: Complete claim arguments without the executable name.

    Returns:
        The engine's process-equivalent exit code and decoded JSON document.

    Independent repositories may execute concurrently. Cross-process correctness still
    comes from the repository-global file lock, and every command performs its normal
    registry, worktree, or journal side effects.
    """
    result, exit_code = engine.dispatch(arguments)
    return ClaimCommandResult(exit_code=exit_code, result=result)
