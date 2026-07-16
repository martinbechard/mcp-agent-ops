# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Reports package identity or starts the installed MCP agent-operations stdio server.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import argparse
import json
import os
from collections.abc import Sequence
from importlib.metadata import version

from mcp_agent_ops.identity import runtime_identity


def main(argv: Sequence[str] | None = None) -> int:
    """Report package identity or run the stdio server.

    Args:
        argv: Optional command arguments without the executable name. An empty sequence
            starts stdio; identity options print installed package evidence and exit.

    Returns:
        Zero after the identity probe or a normal MCP host disconnect.
    """
    parser = argparse.ArgumentParser(prog="mcp-agent-ops")
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('mcp-agent-ops')}",
    )
    identity.add_argument(
        "--identity-json",
        action="store_true",
        help="print deterministic installed runtime identity as JSON and exit",
    )
    arguments = parser.parse_args(argv)
    if arguments.identity_json:
        print(json.dumps(runtime_identity(), sort_keys=True, separators=(",", ":")))
        return 0
    required_runtime_digest = os.environ.get(
        "MCP_AGENT_OPS_REQUIRED_RUNTIME_DIGEST"
    )
    if (
        required_runtime_digest is not None
        and runtime_identity()["runtimeDigest"] != required_runtime_digest
    ):
        parser.error("installed runtime identity does not match the required digest")
    from mcp_agent_ops.adapters.mcp.server import run_server

    run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
