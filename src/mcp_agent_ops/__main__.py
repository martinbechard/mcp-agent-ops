# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Reports package identity or starts the installed MCP agent-operations stdio server.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import argparse
from collections.abc import Sequence
from importlib.metadata import version

from mcp_agent_ops.adapters.mcp.server import run_server


def main(argv: Sequence[str] | None = None) -> int:
    """Report package identity or run the stdio server.

    Args:
        argv: Optional command arguments without the executable name. An empty sequence
            starts stdio; ``--version`` prints the installed package identity and exits.

    Returns:
        Zero after the identity probe or a normal MCP host disconnect.
    """
    parser = argparse.ArgumentParser(prog="mcp-agent-ops")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('mcp-agent-ops')}",
    )
    parser.parse_args(argv)
    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
