# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies structured claim dispatch without cross-repository process serialization.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import argparse
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier, Event, Thread, current_thread

import pytest
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

    assert sorted(result.result["outcome"] for result in results) == [
        "CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED",
        "SHARED_CHECKOUT_ACQUIRED",
    ]
    assert all(result.result["schema_version"] == 2 for result in results)
    status = service.run_claim_command(["--repo", str(repository), "status"])
    assert len(status.result["claims"]) == 1
    assert status.result["claims"][0]["claim_id"] in {"first", "second"}


def test_resource_claim_requires_complete_deadline_evidence(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    first = service.run_claim_command([
        "--repo",
        str(repository),
        "acquire",
        "--claim-id",
        "first",
        "--agent",
        "first",
        "--task",
        "first",
        "--root-task-id",
        "first",
        "--file",
        "README.md",
    ])

    result = service.run_claim_command([
        "--repo",
        str(repository),
        "acquire",
        "--claim-id",
        "resource",
        "--agent",
        "resource",
        "--task",
        "resource",
        "--root-task-id",
        "resource",
        "--resource",
        "git-index:primary",
        "--branch",
        "codex/resource",
    ])

    assert first.exit_code == 0
    assert result.exit_code == 1
    assert result.result["outcome"] == "INVALID_DEADLINE_POLICY"
    assert result.result["rejection"]["reason"] == "resource_timing_required"
    assert not (repository / ".worktrees" / "resource").exists()


def test_stale_legacy_release_re_resolves_after_concurrent_drain_and_migration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    legacy_registry = repository / ".git" / "agent-claims.json"
    legacy_registry.write_text(
        json.dumps({
            "claims": [{
                "claim_id": "legacy-live",
                "agent": "legacy-agent",
                "root_task_id": "legacy-root",
                "task": "legacy claim",
                "files": ["README.md"],
                "trees": [],
                "resources": [],
                "claimed_at": "2026-08-05T10:00:00Z",
                "heartbeat": "2026-08-05T10:00:00Z",
            }]
        }) + "\n",
        encoding="utf-8",
    )
    resolved = Event()
    migration_complete = Event()
    original_resolve = engine._resolve_registry_path

    def pause_stale_release(
        candidate_repository: Path,
        operation: str,
        claim_id: str | None,
    ) -> Path:
        path = original_resolve(candidate_repository, operation, claim_id)
        if current_thread().name == "stale-release":
            resolved.set()
            assert migration_complete.wait(timeout=5)
        return path

    monkeypatch.setattr(engine, "_resolve_registry_path", pause_stale_release)
    stale_results: list[service.ClaimCommandResult] = []
    stale_errors: list[BaseException] = []

    def stale_release() -> None:
        try:
            stale_results.append(service.run_claim_command([
                "--repo",
                str(repository),
                "release",
                "--claim-id",
                "legacy-live",
            ]))
        except BaseException as error:
            stale_errors.append(error)

    waiting_release = Thread(target=stale_release, name="stale-release")
    waiting_release.start()
    assert resolved.wait(timeout=5)
    drained = service.run_claim_command([
        "--repo",
        str(repository),
        "release",
        "--claim-id",
        "legacy-live",
    ])
    migrated = service.run_claim_command([
        "--repo",
        str(repository),
        "acquire",
        "--claim-id",
        "canonical-owner",
        "--agent",
        "canonical-owner",
        "--task",
        "canonical owner",
        "--root-task-id",
        "canonical-owner",
        "--file",
        "README.md",
    ])
    migration_complete.set()
    waiting_release.join(timeout=5)

    assert not waiting_release.is_alive()
    assert drained.result["outcome"] == "RELEASED"
    assert migrated.result["outcome"] == "SHARED_CHECKOUT_ACQUIRED"
    assert stale_errors == []
    assert len(stale_results) == 1
    assert stale_results[0].exit_code == 1
    assert stale_results[0].result["outcome"] == "CLAIM_NOT_FOUND"
    assert legacy_registry.is_dir()
    status = service.run_claim_command(["--repo", str(repository), "status"])
    assert [claim["claim_id"] for claim in status.result["claims"]] == [
        "canonical-owner"
    ]


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows does not preserve an open descriptor after path replacement.",
)
def test_locked_stale_legacy_inode_is_rejected_after_marker_handoff(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    _initialize_repository(repository)
    legacy_registry = repository / ".git" / "agent-claims.json"
    legacy_registry.write_text(
        json.dumps({
            "claims": [{
                "claim_id": "legacy-live",
                "agent": "legacy-agent",
                "root_task_id": "legacy-root",
                "task": "legacy claim",
                "files": ["README.md"],
                "trees": [],
                "resources": [],
                "claimed_at": "2026-08-05T10:00:00Z",
                "heartbeat": "2026-08-05T10:00:00Z",
            }]
        }) + "\n",
        encoding="utf-8",
    )
    stale_descriptor_opened = Event()
    migration_complete = Event()
    original_exclusive_text_file = engine.exclusive_text_file
    stale_legacy_calls = 0

    @contextmanager
    def pause_locked_stale_descriptor(path: Path):
        nonlocal stale_legacy_calls
        if current_thread().name == "stale-inode-release" and path == legacy_registry:
            stale_legacy_calls += 1
            if stale_legacy_calls == 2:
                descriptor = os.open(path, os.O_RDWR)
                with os.fdopen(descriptor, "r+", encoding="utf-8") as locked_file:
                    stale_descriptor_opened.set()
                    assert migration_complete.wait(timeout=5)
                    engine.portalocker.lock(locked_file, engine.portalocker.LOCK_EX)
                    try:
                        yield locked_file
                    finally:
                        engine.portalocker.unlock(locked_file)
                return
        with original_exclusive_text_file(path) as locked_file:
            yield locked_file

    monkeypatch.setattr(engine, "exclusive_text_file", pause_locked_stale_descriptor)
    stale_results: list[service.ClaimCommandResult] = []
    stale_errors: list[BaseException] = []

    def stale_release() -> None:
        try:
            stale_results.append(service.run_claim_command([
                "--repo",
                str(repository),
                "release",
                "--claim-id",
                "legacy-live",
            ]))
        except BaseException as error:
            stale_errors.append(error)

    waiting_release = Thread(target=stale_release, name="stale-inode-release")
    waiting_release.start()
    assert stale_descriptor_opened.wait(timeout=5)
    drained = service.run_claim_command([
        "--repo",
        str(repository),
        "release",
        "--claim-id",
        "legacy-live",
    ])
    migrated = service.run_claim_command([
        "--repo",
        str(repository),
        "acquire",
        "--claim-id",
        "canonical-owner",
        "--agent",
        "canonical-owner",
        "--task",
        "canonical owner",
        "--root-task-id",
        "canonical-owner",
        "--file",
        "README.md",
    ])
    migration_complete.set()
    waiting_release.join(timeout=5)

    assert not waiting_release.is_alive()
    assert drained.result["outcome"] == "RELEASED"
    assert migrated.result["outcome"] == "SHARED_CHECKOUT_ACQUIRED"
    assert stale_errors == []
    assert len(stale_results) == 1
    assert stale_results[0].result["outcome"] == "CLAIM_NOT_FOUND"
    status = service.run_claim_command(["--repo", str(repository), "status"])
    assert [claim["claim_id"] for claim in status.result["claims"]] == [
        "canonical-owner"
    ]
