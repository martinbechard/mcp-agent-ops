# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Preserves the direct claim command while delegating all behavior to the copied engine.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from collections.abc import Sequence

from mcp_agent_ops.claims.engine import main as claim_main


def main(argv: Sequence[str] | None = None) -> int:
    """Run the public claim CLI with stable arguments, output, and exit codes.

    Args:
        argv: Optional arguments without the executable name; process arguments are used
            when absent.

    Returns:
        The stable claim-engine exit code. Commands may mutate the target repository's
        global claim registry, worktrees, and diagnostic journal.
    """
    return claim_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
