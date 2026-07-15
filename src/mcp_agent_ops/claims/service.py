# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Converts copied claim-engine commands into structured in-process results for adapters.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import json
from collections.abc import Sequence
from contextlib import redirect_stdout
from io import StringIO
from threading import Lock
from typing import Any

from pydantic import BaseModel

from mcp_agent_ops.claims import engine


class ClaimCommandResult(BaseModel):
    """Return one copied claim-engine exit code and structured JSON result."""

    exit_code: int
    result: dict[str, Any]


_COMMAND_OUTPUT_LOCK = Lock()


def run_claim_command(arguments: Sequence[str]) -> ClaimCommandResult:
    """Execute the copied claim engine and decode its stable JSON output.

    Args:
        arguments: Complete claim arguments without the executable name.

    Returns:
        The engine's process-equivalent exit code and decoded JSON document.

    The copied engine prints its public result. Standard-output capture is process-global,
    so calls in one MCP process are briefly serialized. Cross-process correctness still
    comes from the repository-global file lock, and every command performs its normal
    registry, worktree, or journal side effects.
    """
    output = StringIO()
    with _COMMAND_OUTPUT_LOCK, redirect_stdout(output):
        exit_code = engine.main(arguments)
    decoded = json.loads(output.getvalue())
    if not isinstance(decoded, dict):
        raise ValueError("Claim engine did not return a JSON object.")
    return ClaimCommandResult(exit_code=exit_code, result=decoded)

