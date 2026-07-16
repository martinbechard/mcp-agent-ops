# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies the server command exposes a non-starting package identity probe.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import subprocess
import sys


def test_server_command_reports_package_version_without_starting_stdio() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_agent_ops", "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == "mcp-agent-ops 0.2.0"
    assert completed.stderr == ""
