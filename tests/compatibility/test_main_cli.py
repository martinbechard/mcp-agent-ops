# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies the server command exposes a non-starting package identity probe.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


def _project_version() -> str:
    project = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    version = project["version"]
    assert isinstance(version, str)
    return version


def test_server_command_reports_package_version_without_starting_stdio() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_agent_ops", "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == f"mcp-agent-ops {_project_version()}"
    assert completed.stderr == ""


def test_server_command_reports_stable_runtime_identity_without_starting_stdio() -> None:
    commands = [
        subprocess.run(
            [sys.executable, "-m", "mcp_agent_ops", "--identity-json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        for _ in range(2)
    ]

    assert all(completed.returncode == 0 for completed in commands)
    assert all(completed.stderr == "" for completed in commands)
    identities = [json.loads(completed.stdout) for completed in commands]
    assert identities[0] == identities[1]
    assert identities[0]["schema"] == "mcp-agent-ops-runtime-identity"
    assert identities[0]["schemaVersion"] == 1
    assert identities[0]["package"] == "mcp-agent-ops"
    assert identities[0]["packageVersion"] == _project_version()
    assert len(identities[0]["runtimeDigest"]) == 64
    assert identities[0]["fileCount"] >= 1


def test_server_command_rejects_a_required_runtime_digest_mismatch() -> None:
    environment = os.environ.copy()
    environment["MCP_AGENT_OPS_REQUIRED_RUNTIME_DIGEST"] = "0" * 64
    completed = subprocess.run(
        [sys.executable, "-m", "mcp_agent_ops"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
        env=environment,
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "runtime identity does not match" in completed.stderr
