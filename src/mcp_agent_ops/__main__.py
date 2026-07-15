# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Starts the installed MCP agent-operations stdio server.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from mcp_agent_ops.adapters.mcp.server import run_server


def main() -> None:
    """Start the stdio server and block until the MCP host disconnects."""
    run_server()


if __name__ == "__main__":
    main()
