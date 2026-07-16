# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies structured claim dispatch without cross-repository process serialization.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from pytest import MonkeyPatch

from mcp_agent_ops.claims import engine, service


def _initialize_repository(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    for arguments in (
        ("init",),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "MCP Test"),
        ("add", "."),
        ("commit", "-m", "baseline"),
    ):
        subprocess.run(
            ["git", "-C", str(path), *arguments],
            check=True,
            capture_output=True,
            text=True,
        )


def test_unrelated_repository_claim_calls_are_not_process_serialized(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    _initialize_repository(first)
    _initialize_repository(second)
    rendezvous = Barrier(2)
    original = engine._status_command

    def synchronized_status(arguments: argparse.Namespace) -> int:
        rendezvous.wait(timeout=2)
        return original(arguments)

    monkeypatch.setattr(engine, "_status_command", synchronized_status)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                service.run_claim_command,
                ["--repo", str(repository), "status"],
            )
            for repository in (first, second)
        ]
        results = [future.result(timeout=5) for future in futures]

    assert [result.result["outcome"] for result in results] == ["STATUS", "STATUS"]
    assert all(result.exit_code == 0 for result in results)


def test_same_repository_claim_calls_preserve_one_authoritative_owner(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    rendezvous = Barrier(2)

    def acquire(claim_id: str) -> service.ClaimCommandResult:
        rendezvous.wait(timeout=2)
        return service.run_claim_command([
            "--repo",
            str(repository),
            "acquire",
            "--claim-id",
            claim_id,
            "--agent",
            claim_id,
            "--task",
            claim_id,
            "--root-task-id",
            claim_id,
            "--file",
            "README.md",
        ])

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(acquire, ("first", "second")))

    assert sorted(result.result["outcome"] for result in results) == ["PRIMARY", "WAIT"]
    status = service.run_claim_command(["--repo", str(repository), "status"])
    assert len(status.result["claims"]) == 1
    assert status.result["claims"][0]["claim_id"] in {"first", "second"}
