#!/usr/bin/env python3
# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Implements command-compatible claim ownership, deadlines, migration, release, and reporting.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import stat
import subprocess
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import IO, Any, Iterator, Sequence, TextIO
from uuid import uuid4

import portalocker
import yaml

from mcp_agent_ops.claims.locking import exclusive_text_file


SUCCESS = 0
ERROR = 1
COORDINATION_REQUIRED_EXIT_CODE = 3
ISOLATION_SETUP_EXIT_CODE = 4
BACKLOG_ROOT_DIRECTORY = "backlog"
WORKTREE_ROOT_DIRECTORY = ".worktrees"
WORKTREE_IGNORE_PATTERN = "/.worktrees/"
CLAIM_STATE_DIRECTORY = ".agent-ops/resource-claim"
CLAIM_STATE_IGNORE_PATTERN = "/.agent-ops/resource-claim/"
REJECTED_CLAIM_STATE_DIRECTORY = ".codex/agent-claim"
ISOLATED_SPARSE_CHECKOUT_PATTERNS = ("/*", "!/backlog/")
REGISTRY_FILE_NAME = "agent-claims.json"
EVENT_DIRECTORY_NAME = "agent-claim-events"
STATE_MARKER_FILE_NAME = "state.json"
STATE_LAYOUT_VERSION = 2
STATE_MARKER_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
RESULT_SCHEMA_VERSION = 2
SUMMARY_SCHEMA_VERSION = 2
REPORT_SCHEMA_VERSION = 2
WORK_ITEM_REPORT_SCHEMA_VERSION = 1
DEFAULT_HOT_DAYS = 2
REGISTRY_LOCK_RETRY_LIMIT = 16
MAX_SCOPE_REASON_LENGTH = 200
MAX_IDENTIFIER_LENGTH = 200
MAX_EXTENSION_EVIDENCE_LENGTH = 1000
_RESOURCE_DEADLINE_CLASS_IDS = (
    "backlog-mutation",
    "main-integration",
    "browser-server",
    "database-port",
    "live-model-evaluation",
)
STALE_HEARTBEAT_HOURS = 24
UTC_DAY_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
SINCE_PATTERN = re.compile(r"^(\d+)([dh])$")
WORKTREE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,198}[A-Za-z0-9_-])?$")
LEGACY_OUTCOME_ALIASES = {
    "PRIMARY": "SHARED_CHECKOUT_ACQUIRED",
    "ISOLATE": "ISOLATED_CHECKOUT_ACQUIRED",
    "RECOVER": "DIRTY_CHECKOUT_RECOVERY_ACQUIRED",
    "WAIT": "CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED",
    "PRIMARY_REQUIRED": "SHARED_CHECKOUT_REQUIRED",
    "ISOLATE_REQUIRED": "ISOLATED_CHECKOUT_SETUP_REQUIRED",
    "RECOVERY_REQUIRED": "DIRTY_CHECKOUT_RECOVERY_AUTHORIZATION_REQUIRED",
}
_RESULT_SINK: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "claim_result_sink",
    default=None,
)


class _ScopeError(ValueError):
    def __init__(
        self,
        message: str,
        offending_scope: str,
        replacement: str,
        reason: str = "invalid_scope",
    ) -> None:
        super().__init__(message)
        self.offending_scope = offending_scope
        self.replacement = replacement
        self.reason = reason


class _DeadlineError(ValueError):
    def __init__(self, message: str, field: str, reason: str) -> None:
        super().__init__(message)
        self.field = field
        self.reason = reason


class _WorkItemError(ValueError):
    def __init__(self, message: str, field: str, reason: str) -> None:
        super().__init__(message)
        self.field = field
        self.reason = reason


class _ClaimStateError(RuntimeError):
    def __init__(self, reason: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.reason = reason
        self.details = details


def _git(worktree: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(worktree), *arguments],
        check=check,
        text=True,
        capture_output=True,
    )


def _repository_root(path: Path) -> Path:
    return Path(_git(path, "rev-parse", "--show-toplevel").stdout.strip()).resolve()


def _git_common_directory(repository: Path) -> Path:
    raw_path = Path(_git(repository, "rev-parse", "--git-common-dir").stdout.strip())
    if not raw_path.is_absolute():
        raw_path = repository / raw_path
    return raw_path.resolve()


def _primary_worktree(repository: Path) -> Path:
    fields = _git(repository, "worktree", "list", "--porcelain", "-z").stdout.split("\0")
    for field in fields:
        if field.startswith("worktree "):
            return Path(field.removeprefix("worktree ")).resolve()
    raise RuntimeError("Git did not report a primary worktree.")


def _canonical_worktree_root(repository: Path) -> Path:
    return (_primary_worktree(repository) / WORKTREE_ROOT_DIRECTORY).resolve()


def _canonical_worktree(repository: Path, claim_id: str) -> Path:
    return (_canonical_worktree_root(repository) / claim_id).resolve()


def _checkout_topology(claim: dict[str, Any]) -> str | None:
    topology = claim.get("checkout_topology")
    if topology in {"primary", "linked"}:
        return str(topology)
    worktree = claim.get("worktree")
    if isinstance(worktree, str):
        worktree_path = Path(worktree).resolve()
        try:
            return "primary" if worktree_path == _primary_worktree(worktree_path) else "linked"
        except (OSError, RuntimeError, subprocess.CalledProcessError):
            pass
    mode = claim.get("mode")
    if mode == "isolated":
        return "linked"
    if mode in {"primary", "recovery"}:
        return "primary"
    return None


def _worktree_root_is_ignored(repository: Path) -> bool:
    primary_worktree = _primary_worktree(repository)
    probe = f"{WORKTREE_ROOT_DIRECTORY}/.agent-claim-ignore-probe"
    ignored = _git(
        primary_worktree,
        "check-ignore",
        "--quiet",
        "--no-index",
        "--",
        probe,
        check=False,
    )
    return ignored.returncode == SUCCESS


def _claim_id_is_safe_worktree_component(claim_id: str) -> bool:
    return bool(WORKTREE_COMPONENT_PATTERN.fullmatch(claim_id))


def _worktree_owned_path(repository: Path, relative: str) -> Path:
    """Return a primary-worktree path after rejecting symlinked ancestors."""
    primary = _primary_worktree(repository)
    candidate = primary
    for component in Path(relative).parts:
        candidate /= component
        if os.path.lexists(candidate) and candidate.is_symlink():
            raise _ClaimStateError(
                "unsafe_state_path",
                "Claim-state paths must not contain symbolic links.",
                path=str(candidate),
            )
    return candidate


def _state_root(repository: Path) -> Path:
    return _worktree_owned_path(repository, CLAIM_STATE_DIRECTORY)


def _registry_path(repository: Path) -> Path:
    return _state_root(repository) / REGISTRY_FILE_NAME


def _legacy_registry_path(repository: Path) -> Path:
    return _worktree_owned_path(
        repository, f"{REJECTED_CLAIM_STATE_DIRECTORY}/{REGISTRY_FILE_NAME}"
    )


def _legacy_events_path(repository: Path) -> Path:
    return _worktree_owned_path(
        repository, f"{REJECTED_CLAIM_STATE_DIRECTORY}/{EVENT_DIRECTORY_NAME}"
    )


def _state_marker_path(repository: Path) -> Path:
    return _state_root(repository) / STATE_MARKER_FILE_NAME


def _registry_payload(
    path: Path,
    *,
    locked_file: IO[str] | None = None,
) -> dict[str, Any]:
    try:
        if locked_file is None:
            raw = path.read_text(encoding="utf-8")
        else:
            locked_file.seek(0)
            raw = locked_file.read()
        data = json.loads(raw) if raw else {"claims": []}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _ClaimStateError(
            "invalid_registry",
            f"Claim registry is unreadable or invalid: {path}: {error}",
            registry=str(path),
        ) from error
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        raise _ClaimStateError(
            "invalid_registry",
            f"Claim registry has an invalid claims field: {path}",
            registry=str(path),
        )
    return data


def _state_marker(repository: Path) -> dict[str, Any] | None:
    marker_path = _state_marker_path(repository)
    if not marker_path.exists():
        return None
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _ClaimStateError(
            "invalid_state_marker",
            f"Claim-state marker is unreadable or invalid: {marker_path}: {error}",
            marker=str(marker_path),
        ) from error
    if (
        not isinstance(marker, dict)
        or marker.get("schema_version") != STATE_MARKER_SCHEMA_VERSION
        or marker.get("state_layout_version") != STATE_LAYOUT_VERSION
        or marker.get("migration_status") not in {"in_progress", "complete"}
        or marker.get("origin") not in {"fresh", "legacy"}
    ):
        raise _ClaimStateError(
            "invalid_state_marker",
            f"Claim-state marker has an unsupported contract: {marker_path}",
            marker=str(marker_path),
        )
    return marker


def _write_state_marker(repository: Path, status: str, origin: str) -> None:
    marker = {
        "schema_version": STATE_MARKER_SCHEMA_VERSION,
        "state_layout_version": STATE_LAYOUT_VERSION,
        "migration_status": status,
        "origin": origin,
    }
    _atomic_write(
        _state_marker_path(repository),
        (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _create_empty_registry(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, b'{\n  "claims": []\n}\n')
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _legacy_marker_payload(kind: str) -> bytes:
    marker = {
        "schema_version": STATE_MARKER_SCHEMA_VERSION,
        "state_layout_version": STATE_LAYOUT_VERSION,
        "migrated": kind,
    }
    return (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _legacy_registry_is_marker(path: Path) -> bool:
    marker = path / STATE_MARKER_FILE_NAME
    try:
        if path.is_file():
            return path.read_bytes() == _legacy_marker_payload("registry")
        return (
            path.is_dir()
            and marker.is_file()
            and marker.read_bytes() == _legacy_marker_payload("registry")
        )
    except OSError:
        return False


def _legacy_events_is_marker(path: Path) -> bool:
    try:
        return path.is_file() and path.read_bytes() == _legacy_marker_payload("events")
    except OSError:
        return False


def _windows_legacy_tombstone_required() -> bool:
    return os.name == "nt"


def _install_legacy_registry_marker(path: Path) -> None:
    if _legacy_registry_is_marker(path):
        return
    if os.path.lexists(path):
        raise _ClaimStateError(
            "contradictory_dual_state",
            f"Legacy registry path has an unexpected type or content: {path}",
            legacy_registry=str(path),
        )
    path.mkdir()
    (path / STATE_MARKER_FILE_NAME).write_bytes(_legacy_marker_payload("registry"))


def _install_legacy_events_marker(path: Path) -> None:
    if _legacy_events_is_marker(path):
        return
    if os.path.lexists(path):
        raise _ClaimStateError(
            "contradictory_dual_state",
            f"Legacy event path has an unexpected type or content: {path}",
            legacy_events=str(path),
        )
    path.write_bytes(_legacy_marker_payload("events"))


def _write_locked_legacy_registry_tombstone(
    legacy_file: IO[str],
    legacy_registry: Path,
) -> None:
    """Replace validated empty legacy state through its locked descriptor."""
    legacy_file.flush()
    descriptor = legacy_file.fileno()
    if os.name == "nt":
        import msvcrt

        msvcrt.setmode(descriptor, os.O_BINARY)
    payload = _legacy_marker_payload("registry")
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError(f"legacy registry tombstone write failed: {legacy_registry}")
        remaining = remaining[written:]
    os.ftruncate(descriptor, len(payload))
    os.fsync(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.read(descriptor, len(payload) + 1) != payload:
        raise OSError(f"legacy registry tombstone verification failed: {legacy_registry}")
    legacy_file.seek(0)


def _require_exact_empty_legacy_payload(
    legacy_data: dict[str, Any],
    legacy_registry: Path,
) -> None:
    if legacy_data["claims"]:
        raise _ClaimStateError(
            "live_legacy_claims_require_drain",
            "Release every live legacy claim before migrating claim state.",
            legacy_registry=str(legacy_registry),
            live_claim_ids=[
                str(claim.get("claim_id")) for claim in legacy_data["claims"]
            ],
            allowed_operation="release",
        )
    if legacy_data != {"claims": []}:
        raise _ClaimStateError(
            "contradictory_dual_state",
            "The legacy registry is not the exact empty state required for retirement.",
            legacy_registry=str(legacy_registry),
        )


def _tombstone_windows_legacy_registry(
    repository: Path,
    locked_legacy_file: IO[str] | None,
    captured_payload: dict[str, Any] | None,
) -> None:
    """Install the Windows tombstone without changing the legacy registry inode."""
    legacy_registry = _legacy_registry_path(repository)
    if _legacy_registry_is_marker(legacy_registry):
        return

    if locked_legacy_file is not None:
        if not _locked_file_matches_path(legacy_registry, locked_legacy_file):
            raise _ClaimStateError(
                "contradictory_dual_state",
                "The locked legacy registry no longer owns its migration path.",
                legacy_registry=str(legacy_registry),
            )
        legacy_data = _registry_payload(
            legacy_registry,
            locked_file=locked_legacy_file,
        )
        if captured_payload is not None and legacy_data != captured_payload:
            raise _ClaimStateError(
                "contradictory_dual_state",
                "The locked legacy registry changed after its migration payload was captured.",
                legacy_registry=str(legacy_registry),
            )
        _require_exact_empty_legacy_payload(legacy_data, legacy_registry)
        _write_locked_legacy_registry_tombstone(
            locked_legacy_file,
            legacy_registry,
        )
        return

    try:
        with exclusive_text_file(legacy_registry, create=False) as legacy_file:
            if not _locked_file_matches_path(legacy_registry, legacy_file):
                raise _ClaimStateError(
                    "contradictory_dual_state",
                    "Interrupted migration found an unstable legacy registry path.",
                    legacy_registry=str(legacy_registry),
                )
            legacy_data = _registry_payload(
                legacy_registry,
                locked_file=legacy_file,
            )
            _require_exact_empty_legacy_payload(legacy_data, legacy_registry)
            _write_locked_legacy_registry_tombstone(legacy_file, legacy_registry)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as error:
        raise _ClaimStateError(
            "contradictory_dual_state",
            "Interrupted migration is missing its exact legacy registry marker.",
            legacy_registry=str(legacy_registry),
        ) from error


def _windows_in_progress_live_legacy_registry(
    repository: Path,
    operation: str,
    claim_id: str | None,
) -> Path | None:
    """Route restored live state to the legacy drain-only release boundary."""
    legacy_registry = _legacy_registry_path(repository)
    if _legacy_registry_is_marker(legacy_registry) or not legacy_registry.is_file():
        return None
    try:
        with exclusive_text_file(legacy_registry, create=False) as legacy_file:
            if not _locked_file_matches_path(legacy_registry, legacy_file):
                return None
            data = _registry_payload(legacy_registry, locked_file=legacy_file)
            if not data["claims"]:
                return None
            live_ids = [str(claim.get("claim_id")) for claim in data["claims"]]
            if operation == "release" and claim_id in live_ids:
                return legacy_registry
            raise _ClaimStateError(
                "live_legacy_claims_require_drain",
                "The legacy registry is drain-only until every live claim is released.",
                legacy_registry=str(legacy_registry),
                live_claim_ids=live_ids,
                allowed_operation="release",
            )
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return None


def _move_legacy_events(repository: Path) -> None:
    state_root = _state_root(repository)
    events_path = state_root / EVENT_DIRECTORY_NAME
    legacy_events = _legacy_events_path(repository)

    if _legacy_events_is_marker(legacy_events):
        events_path.mkdir(parents=True, exist_ok=True)
    elif legacy_events.exists():
        if not legacy_events.is_dir() or events_path.exists():
            raise _ClaimStateError(
                "contradictory_dual_state",
                "Both legacy and canonical event-history locations contain state.",
                legacy_events=str(legacy_events),
                canonical_events=str(events_path),
            )
        os.rename(legacy_events, events_path)
    else:
        events_path.mkdir(parents=True, exist_ok=True)

    if os.environ.get("AGENT_CLAIM_TEST_FAIL_MIGRATION_AFTER_EVENTS") == "1":
        raise OSError("simulated interruption after moving legacy event history")


@contextmanager
def _migration_lock(repository: Path) -> Iterator[TextIO]:
    registry_path = _registry_path(repository)
    if not registry_path.exists():
        try:
            _create_empty_registry(registry_path)
        except FileExistsError:
            pass
    with exclusive_text_file(registry_path) as registry_file:
        yield registry_file


def _finish_legacy_migration(
    repository: Path,
    registry_file: TextIO,
    *,
    legacy_data: dict[str, Any] | None = None,
    locked_legacy_file: IO[str] | None = None,
) -> None:
    registry_path = _state_root(repository) / REGISTRY_FILE_NAME
    legacy_registry = _legacy_registry_path(repository)
    legacy_events = _legacy_events_path(repository)

    if not registry_path.exists():
        _create_empty_registry(registry_path)
    if _registry_payload(registry_path, locked_file=registry_file)["claims"]:
        raise _ClaimStateError(
            "contradictory_dual_state",
            "Interrupted migration found live canonical claims before the legacy boundary completed.",
            canonical_registry=str(registry_path),
            legacy_registry=str(legacy_registry),
        )

    if _windows_legacy_tombstone_required():
        _tombstone_windows_legacy_registry(
            repository,
            locked_legacy_file,
            legacy_data,
        )
        _move_legacy_events(repository)
        _install_legacy_events_marker(legacy_events)
        _write_state_marker(repository, "complete", "legacy")
        return

    _move_legacy_events(repository)

    if _legacy_registry_is_marker(legacy_registry):
        pass
    elif legacy_registry.exists():
        if legacy_data is None:
            legacy_data = _registry_payload(legacy_registry)
        if legacy_data["claims"]:
            raise _ClaimStateError(
                "live_legacy_claims_require_drain",
                "Release every live legacy claim before migrating claim state.",
                legacy_registry=str(legacy_registry),
                live_claim_ids=[str(claim.get("claim_id")) for claim in legacy_data["claims"]],
            )
        legacy_registry.unlink()
    _install_legacy_registry_marker(legacy_registry)
    _install_legacy_events_marker(legacy_events)
    _write_state_marker(repository, "complete", "legacy")


def _resolve_registry_path_once(
    repository: Path,
    operation: str,
    claim_id: str | None,
) -> Path | None:
    registry_path = _registry_path(repository)
    marker = _state_marker(repository)

    if marker and marker["migration_status"] == "complete":
        if not registry_path.exists():
            raise _ClaimStateError(
                "canonical_registry_missing",
                "The completed claim-state marker has no canonical registry.",
                registry=str(registry_path),
            )
        legacy_registry = registry_path.parent / ".completed-legacy-registry-boundary"
        legacy_events = registry_path.parent / ".completed-legacy-events-boundary"
        # A durable complete marker is the permission boundary. Steady-state
        # operations must not probe harness-owned rejected storage.
        return registry_path

    legacy_registry = _legacy_registry_path(repository)
    legacy_events = _legacy_events_path(repository)

    if marker and marker["migration_status"] == "in_progress":
        if _windows_legacy_tombstone_required():
            live_legacy_registry = _windows_in_progress_live_legacy_registry(
                repository,
                operation,
                claim_id,
            )
            if live_legacy_registry is not None:
                return live_legacy_registry
        try:
            with _migration_lock(repository) as registry_file:
                _finish_legacy_migration(repository, registry_file)
        except _ClaimStateError:
            raise
        except OSError as error:
            raise _ClaimStateError(
                "migration_interrupted",
                f"Claim-state migration was interrupted and can be retried: {error}",
                canonical_registry=str(registry_path),
                legacy_registry=str(legacy_registry),
            ) from error
        return registry_path

    if registry_path.exists() and (
        os.path.lexists(legacy_registry) or os.path.lexists(legacy_events)
    ):
        raise _ClaimStateError(
            "contradictory_dual_state",
            "Both legacy and canonical claim registries exist without one storage alias.",
            canonical_registry=str(registry_path),
            legacy_registry=str(legacy_registry),
        )

    if not os.path.lexists(legacy_registry) and os.path.lexists(legacy_events):
        raise _ClaimStateError(
            "contradictory_dual_state",
            "Legacy event history exists without its legacy registry.",
            legacy_registry=str(legacy_registry),
            legacy_events=str(legacy_events),
        )

    if os.path.lexists(legacy_registry):
        verified_lock = False
        try:
            with exclusive_text_file(legacy_registry, create=False) as legacy_file:
                if not _locked_file_matches_path(legacy_registry, legacy_file):
                    return None
                verified_lock = True
                legacy_file.seek(0)
                raw = legacy_file.read()
                try:
                    data = json.loads(raw) if raw else {"claims": []}
                except json.JSONDecodeError as error:
                    raise _ClaimStateError(
                        "invalid_registry",
                        f"Legacy claim registry contains invalid JSON: {legacy_registry}",
                        legacy_registry=str(legacy_registry),
                    ) from error
                if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
                    raise _ClaimStateError(
                        "invalid_registry",
                        f"Legacy claim registry has an invalid claims field: {legacy_registry}",
                        legacy_registry=str(legacy_registry),
                    )
                claims = data["claims"]
                if claims:
                    live_ids = [str(claim.get("claim_id")) for claim in claims]
                    if operation == "release" and claim_id in live_ids:
                        return legacy_registry
                    raise _ClaimStateError(
                        "live_legacy_claims_require_drain",
                        "The legacy registry is drain-only until every live claim is released.",
                        legacy_registry=str(legacy_registry),
                        live_claim_ids=live_ids,
                        allowed_operation="release",
                    )
                if _windows_legacy_tombstone_required():
                    _require_exact_empty_legacy_payload(data, legacy_registry)
                _state_root(repository).mkdir(parents=True, exist_ok=True)
                _write_state_marker(repository, "in_progress", "legacy")
                try:
                    with _migration_lock(repository) as registry_file:
                        _finish_legacy_migration(
                            repository,
                            registry_file,
                            legacy_data=data,
                            locked_legacy_file=legacy_file,
                        )
                except _ClaimStateError:
                    raise
                except OSError as error:
                    raise _ClaimStateError(
                        "migration_interrupted",
                        f"Claim-state migration was interrupted and can be retried: {error}",
                        canonical_registry=str(registry_path),
                        legacy_registry=str(legacy_registry),
                    ) from error
                return registry_path
        except (OSError, portalocker.LockException):
            if not verified_lock and _claim_path_handoff_occurred(legacy_registry):
                return None
            raise

    with _migration_lock(repository) as registry_file:
        current_marker = _state_marker(repository)
        if current_marker is not None:
            if current_marker["migration_status"] != "complete":
                raise _ClaimStateError(
                    "migration_interrupted",
                    "Claim-state migration is incomplete; retry the mutating operation.",
                    canonical_registry=str(registry_path),
                    legacy_registry=str(legacy_registry),
                )
            return registry_path
        _registry_payload(registry_path, locked_file=registry_file)
        _write_state_marker(repository, "complete", "fresh")
    return registry_path


def _resolve_registry_path(
    repository: Path,
    operation: str,
    claim_id: str | None,
) -> Path:
    """Resolve mutation storage, retrying boundedly when migration changes its inode."""
    for _attempt in range(REGISTRY_LOCK_RETRY_LIMIT):
        registry_path = _resolve_registry_path_once(repository, operation, claim_id)
        if registry_path is not None:
            return registry_path
    raise _ClaimStateError(
        "registry_resolution_race",
        "Claim registry storage kept changing while its migration lock was acquired.",
        operation=operation,
        claim_id=claim_id,
    )


def _read_only_registry_once(repository: Path) -> tuple[Path, dict[str, Any]] | None:
    """Read claim state under its existing lock without creating or migrating storage."""
    registry_path = _registry_path(repository)
    marker = _state_marker(repository)

    if marker and marker["migration_status"] == "complete":
        if not registry_path.exists():
            raise _ClaimStateError(
                "canonical_registry_missing",
                "The completed claim-state marker has no canonical registry.",
                registry=str(registry_path),
            )
        legacy_registry = registry_path.parent / ".completed-legacy-registry-boundary"
        legacy_events = registry_path.parent / ".completed-legacy-events-boundary"
    else:
        legacy_registry = _legacy_registry_path(repository)
        legacy_events = _legacy_events_path(repository)
        if marker and marker["migration_status"] == "in_progress":
            raise _ClaimStateError(
                "migration_interrupted",
                "Claim-state migration is incomplete; retry with the next mutating operation.",
                canonical_registry=str(registry_path),
                legacy_registry=str(legacy_registry),
            )
    if not (marker and marker["migration_status"] == "complete") and registry_path.exists() and (
        os.path.lexists(legacy_registry) or os.path.lexists(legacy_events)
    ):
        raise _ClaimStateError(
            "contradictory_dual_state",
            "Both legacy and canonical claim registries exist without a completed boundary.",
            canonical_registry=str(registry_path),
            legacy_registry=str(legacy_registry),
        )
    elif not registry_path.exists() and os.path.lexists(legacy_registry):
        if _legacy_registry_is_marker(legacy_registry):
            raise _ClaimStateError(
                "migration_interrupted",
                "A legacy registry marker exists without a completed canonical boundary.",
                canonical_registry=str(registry_path),
                legacy_registry=str(legacy_registry),
            )
        verified_lock = False
        try:
            with exclusive_text_file(legacy_registry, create=False) as legacy_file:
                if not _locked_file_matches_path(legacy_registry, legacy_file):
                    return None
                verified_lock = True
                legacy_file.seek(0)
                raw = legacy_file.read()
                try:
                    data = json.loads(raw) if raw else {"claims": []}
                except json.JSONDecodeError as error:
                    raise _ClaimStateError(
                        "invalid_registry",
                        f"Legacy claim registry contains invalid JSON: {legacy_registry}",
                        legacy_registry=str(legacy_registry),
                    ) from error
                if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
                    raise _ClaimStateError(
                        "invalid_registry",
                        f"Legacy claim registry has an invalid claims field: {legacy_registry}",
                        legacy_registry=str(legacy_registry),
                    )
                if data["claims"]:
                    raise _ClaimStateError(
                        "live_legacy_claims_require_drain",
                        "The legacy registry is drain-only until every live claim is released.",
                        legacy_registry=str(legacy_registry),
                        live_claim_ids=[str(claim.get("claim_id")) for claim in data["claims"]],
                        allowed_operation="release",
                    )
                return registry_path, {"claims": []}
        except (OSError, portalocker.LockException):
            if not verified_lock and _claim_path_handoff_occurred(legacy_registry):
                return None
            raise

    if not os.path.lexists(legacy_registry) and os.path.lexists(legacy_events):
        raise _ClaimStateError(
            "contradictory_dual_state",
            "Legacy event history exists without its legacy registry.",
            legacy_registry=str(legacy_registry),
            legacy_events=str(legacy_events),
        )

    if not registry_path.exists():
        return registry_path, {"claims": []}
    with exclusive_text_file(registry_path) as registry_file:
        try:
            registry_file.seek(0)
            raw = registry_file.read()
            data = json.loads(raw) if raw else {"claims": []}
            if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
                raise _ClaimStateError(
                    "invalid_registry",
                    f"Claim registry has an invalid claims field: {registry_path}",
                    registry=str(registry_path),
                )
            return registry_path, data
        except json.JSONDecodeError as error:
            raise _ClaimStateError(
                "invalid_registry",
                f"Claim registry contains invalid JSON: {registry_path}",
                registry=str(registry_path),
            ) from error
        finally:
            pass


def _read_only_registry(repository: Path) -> tuple[Path, dict[str, Any]]:
    """Read stable claim state, retrying boundedly across legacy migration."""
    for _attempt in range(REGISTRY_LOCK_RETRY_LIMIT):
        snapshot = _read_only_registry_once(repository)
        if snapshot is not None:
            return snapshot
    raise _ClaimStateError(
        "registry_read_race",
        "Claim registry storage kept changing while its read lock was acquired.",
    )


def _journal_paths(common_directory: Path) -> tuple[Path, Path, Path, Path]:
    root = common_directory / EVENT_DIRECTORY_NAME
    return root, root / "hot", root / "archive", root / "journal"


def _locked_file_identity_is_current(
    descriptor_status: os.stat_result,
    path_status: os.stat_result | None,
    *,
    platform_name: str,
) -> bool:
    if (
        path_status is None
        or not stat.S_ISREG(descriptor_status.st_mode)
        or not stat.S_ISREG(path_status.st_mode)
    ):
        return False
    if platform_name == "nt":
        return True
    return (
        descriptor_status.st_nlink > 0
        and path_status.st_nlink > 0
        and (descriptor_status.st_dev, descriptor_status.st_ino)
        == (path_status.st_dev, path_status.st_ino)
    )


def _locked_file_matches_path(path: Path, locked_file: IO[str]) -> bool:
    try:
        descriptor_status = os.fstat(locked_file.fileno())
    except OSError:
        return False
    try:
        path_status = path.stat(follow_symlinks=False)
    except OSError:
        path_status = None
    return _locked_file_identity_is_current(
        descriptor_status,
        path_status,
        platform_name=os.name,
    )


def _claim_path_handoff_occurred(path: Path) -> bool:
    try:
        return not path.is_file()
    except OSError:
        return True


@contextmanager
def _locked_registry_file(
    repository: Path,
    operation: str,
    claim_id: str | None = None,
) -> Iterator[tuple[Path, TextIO]]:
    for _attempt in range(REGISTRY_LOCK_RETRY_LIMIT):
        registry_path = _resolve_registry_path(repository, operation, claim_id)
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        verified_lock = False
        try:
            with exclusive_text_file(registry_path, create=False) as registry_file:
                if not _locked_file_matches_path(registry_path, registry_file):
                    continue
                verified_lock = True
                yield registry_path, registry_file
                return
        except (OSError, portalocker.LockException):
            if not verified_lock and _claim_path_handoff_occurred(registry_path):
                continue
            raise
    raise _ClaimStateError(
        "registry_lock_race",
        "Claim registry storage kept changing while its operational lock was acquired.",
        operation=operation,
        claim_id=claim_id,
    )


@contextmanager
def _locked_registry(
    repository: Path,
    operation: str,
    claim_id: str | None = None,
) -> Iterator[tuple[Path, dict[str, Any], TextIO]]:
    with _locked_registry_file(repository, operation, claim_id) as (registry_path, registry_file):
        try:
            registry_file.seek(0)
            raw_registry = registry_file.read()
            data = json.loads(raw_registry) if raw_registry else {"claims": []}
            if not isinstance(data.get("claims"), list):
                raise ValueError(f"Invalid claim registry: {registry_path}")
            yield registry_path, data, registry_file
        finally:
            pass


@contextmanager
def _maintenance_lock(common_directory: Path) -> Iterator[None]:
    root, _hot, _archive, _journal = _journal_paths(common_directory)
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_text_file(root / "maintenance.lock"):
        yield


def _write_registry(registry_file: TextIO, data: dict[str, Any]) -> None:
    registry_file.seek(0)
    registry_file.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
    registry_file.truncate()
    registry_file.flush()
    os.fsync(registry_file.fileno())


def _now() -> datetime:
    override = os.environ.get("AGENT_CLAIM_TEST_NOW")
    if override:
        parsed = datetime.fromisoformat(override.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _timestamp() -> str:
    return _format_timestamp(_now())


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deadline_policy_seconds(
    policy: dict[str, Any],
    field: str,
    context: str,
    *,
    allow_zero: bool = False,
) -> int:
    value = policy.get(field)
    valid = isinstance(value, int) and not isinstance(value, bool)
    valid = valid and (value >= 0 if allow_zero else value > 0)
    if not valid:
        qualifier = "non-negative" if allow_zero else "positive"
        raise _DeadlineError(
            f"{context}.{field} must be a {qualifier} integer.",
            field,
            "invalid_project_deadline_policy",
        )
    return value


def _load_deadline_policy(repository: Path) -> dict[str, Any]:
    project_path = repository / "PROJECT.yaml"
    if not project_path.is_file():
        raise _DeadlineError(
            "PROJECT.yaml is required for named resource acquisition.",
            "PROJECT.yaml",
            "project_policy_missing",
        )
    try:
        project = yaml.safe_load(project_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise _DeadlineError(
            f"PROJECT.yaml resource deadline policy is unreadable or invalid: {error}.",
            "PROJECT.yaml",
            "project_policy_invalid",
        ) from error
    coordination = project.get("resource_coordination") if isinstance(project, dict) else None
    if not isinstance(coordination, dict) or coordination.get("selected") != "resource-claim":
        raise _DeadlineError(
            "PROJECT.yaml resource_coordination must select resource-claim for named resource acquisition.",
            "resource_coordination.selected",
            "resource_coordination_not_selected",
        )
    policy = coordination.get("deadline_policy")
    if not isinstance(policy, dict) or set(policy) != {"resource_classes", "resource_overrides"}:
        raise _DeadlineError(
            "resource_coordination.deadline_policy keys must be exactly: resource_classes, resource_overrides.",
            "resource_coordination.deadline_policy",
            "invalid_project_deadline_policy",
        )
    classes = policy.get("resource_classes")
    if not isinstance(classes, dict) or set(classes) != set(_RESOURCE_DEADLINE_CLASS_IDS):
        raise _DeadlineError(
            "resource_coordination.deadline_policy.resource_classes keys must be exactly: "
            + ", ".join(_RESOURCE_DEADLINE_CLASS_IDS)
            + ".",
            "resource_coordination.deadline_policy.resource_classes",
            "invalid_project_deadline_policy",
        )
    normalized_classes: dict[str, dict[str, int]] = {}
    for class_id in _RESOURCE_DEADLINE_CLASS_IDS:
        class_policy = classes[class_id]
        context = f"resource_coordination.deadline_policy.resource_classes.{class_id}"
        if not isinstance(class_policy, dict) or set(class_policy) != {
            "maximum_duration_seconds",
            "cleanup_grace_seconds",
        }:
            raise _DeadlineError(
                f"{context} keys must be exactly: maximum_duration_seconds, cleanup_grace_seconds.",
                context,
                "invalid_project_deadline_policy",
            )
        normalized_classes[class_id] = {
            "maximum_duration_seconds": _deadline_policy_seconds(
                class_policy,
                "maximum_duration_seconds",
                context,
            ),
            "cleanup_grace_seconds": _deadline_policy_seconds(
                class_policy,
                "cleanup_grace_seconds",
                context,
                allow_zero=True,
            ),
        }
    overrides = policy.get("resource_overrides")
    if not isinstance(overrides, dict):
        raise _DeadlineError(
            "resource_coordination.deadline_policy.resource_overrides must be a mapping.",
            "resource_coordination.deadline_policy.resource_overrides",
            "invalid_project_deadline_policy",
        )
    normalized_overrides: dict[str, dict[str, Any]] = {}
    for raw_resource_id, override in overrides.items():
        resource_id = raw_resource_id.strip() if isinstance(raw_resource_id, str) else ""
        context = f"resource_coordination.deadline_policy.resource_overrides.{resource_id}"
        if not resource_id or resource_id != raw_resource_id or len(resource_id) > MAX_IDENTIFIER_LENGTH:
            raise _DeadlineError(
                "resource override ids must be canonical non-empty strings of at most 200 characters.",
                "resource_id",
                "invalid_project_deadline_policy",
            )
        if not isinstance(override, dict) or set(override) != {
            "resource_class",
            "maximum_duration_seconds",
            "cleanup_grace_seconds",
        }:
            raise _DeadlineError(
                f"{context} keys must be exactly: resource_class, maximum_duration_seconds, cleanup_grace_seconds.",
                context,
                "invalid_project_deadline_policy",
            )
        resource_class = override.get("resource_class")
        if resource_class not in normalized_classes:
            raise _DeadlineError(
                f"{context}.resource_class must name a configured resource class.",
                "resource_class",
                "invalid_project_deadline_policy",
            )
        normalized_overrides[resource_id] = {
            "resource_class": resource_class,
            "maximum_duration_seconds": _deadline_policy_seconds(
                override,
                "maximum_duration_seconds",
                context,
            ),
            "cleanup_grace_seconds": _deadline_policy_seconds(
                override,
                "cleanup_grace_seconds",
                context,
                allow_zero=True,
            ),
        }
    return {"resource_classes": normalized_classes, "resource_overrides": normalized_overrides}


def _deadline_request_from_args(
    args: argparse.Namespace,
    resources: Sequence[str],
    repository: Path,
) -> dict[str, Any] | None:
    argument_names = (
        "resource_class",
        "resource_id",
        "expected_duration_seconds",
        "requested_hard_stop_duration_seconds",
    )
    values = {name: getattr(args, name, None) for name in argument_names}
    supplied = [name for name, value in values.items() if value is not None]
    if len(resources) > 1:
        raise _DeadlineError(
            "A claim may acquire exactly one named resource.",
            "resource",
            "multiple_resources_not_supported",
        )
    if not resources and not supplied:
        return None
    if not resources:
        raise _DeadlineError(
            "Resource timing arguments require exactly one named --resource.",
            "resource",
            "timing_without_resource",
        )
    if not supplied:
        raise _DeadlineError(
            "Named resource acquisition requires complete timing evidence.",
            "resource",
            "resource_timing_required",
        )
    if len(supplied) != len(argument_names):
        missing = sorted(set(argument_names) - set(supplied))
        raise _DeadlineError(
            f"Resource timing arguments must be supplied together; missing: {', '.join(missing)}.",
            ",".join(missing),
            "incomplete_deadline_arguments",
        )

    resource_class = values["resource_class"].strip() if isinstance(values["resource_class"], str) else None
    resource_id = values["resource_id"].strip() if isinstance(values["resource_id"], str) else None
    if not isinstance(resource_class, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", resource_class):
        raise _DeadlineError(
            "resource class must be a stable lowercase identifier containing letters, digits, and hyphens.",
            "resource_class",
            "invalid_resource_class",
        )
    if not isinstance(resource_id, str) or resource_id != resources[0]:
        raise _DeadlineError(
            "resource id must exactly match one acquired --resource value.",
            "resource_id",
            "resource_id_not_acquired",
        )

    expected = values["expected_duration_seconds"]
    hard_stop = values["requested_hard_stop_duration_seconds"]
    for field, value in (
        ("expected_duration_seconds", expected),
        ("requested_hard_stop_duration_seconds", hard_stop),
    ):
        if not isinstance(value, int) or value <= 0:
            raise _DeadlineError(
                f"{field.replace('_', ' ')} must be a positive integer.",
                field,
                "invalid_duration",
            )
    if expected > hard_stop:
        raise _DeadlineError(
            "expected duration must not exceed requested hard stop.",
            "expected_duration_seconds",
            "expected_exceeds_hard_stop",
        )
    policy = _load_deadline_policy(repository)
    class_policy = policy["resource_classes"].get(resource_class)
    if class_policy is None:
        raise _DeadlineError(
            "resource class must name a configured PROJECT.yaml resource class.",
            "resource_class",
            "resource_class_not_configured",
        )
    override = policy["resource_overrides"].get(resource_id)
    if override is not None and override["resource_class"] != resource_class:
        raise _DeadlineError(
            f"resource id {resource_id} is configured for resource class {override['resource_class']}.",
            "resource_class",
            "resource_override_class_mismatch",
        )
    resolved = override or class_policy
    maximum = resolved["maximum_duration_seconds"]
    cleanup_grace = resolved["cleanup_grace_seconds"]
    if hard_stop > maximum:
        raise _DeadlineError(
            "requested hard stop must not exceed configured maximum.",
            "requested_hard_stop_duration_seconds",
            "hard_stop_exceeds_maximum",
        )

    return {
        "resource_class": resource_class,
        "resource_id": resource_id,
        "expected_duration_seconds": expected,
        "requested_hard_stop_duration_seconds": hard_stop,
        "configured_maximum_duration_seconds": maximum,
        "cleanup_grace_seconds": cleanup_grace,
    }


def _deadline_from_request(request: dict[str, Any], acquired_at: str) -> dict[str, Any]:
    acquired = _parse_timestamp(acquired_at)
    hard_stop = request["requested_hard_stop_duration_seconds"]
    cleanup_grace = request["cleanup_grace_seconds"]
    expected = request["expected_duration_seconds"]
    hard_stop_at = acquired + timedelta(seconds=hard_stop)
    return {
        **request,
        "acquired_at": acquired_at,
        "expected_release_at": _format_timestamp(acquired + timedelta(seconds=expected)),
        "hard_stop_at": _format_timestamp(hard_stop_at),
        "cleanup_grace_ends_at": _format_timestamp(
            hard_stop_at + timedelta(seconds=cleanup_grace)
        ),
        "extensions": [],
    }


def _deadline_status(deadline: dict[str, Any], evaluated_at: datetime) -> dict[str, Any]:
    hard_stop_at = _parse_timestamp(str(deadline["hard_stop_at"]))
    cleanup_grace_ends_at = _parse_timestamp(str(deadline["cleanup_grace_ends_at"]))
    overdue = evaluated_at >= hard_stop_at
    cleanup_elapsed = evaluated_at >= cleanup_grace_ends_at
    return {
        "evaluated_at": _format_timestamp(evaluated_at),
        "overdue": overdue,
        "cleanup_grace": {
            "seconds": deadline["cleanup_grace_seconds"],
            "ends_at": deadline["cleanup_grace_ends_at"],
            "active": overdue and not cleanup_elapsed,
            "elapsed": cleanup_elapsed,
        },
        "stopped_owner_actionability_inputs": {
            "owner_stopped": None,
            "immediately_actionable_when_stopped": True,
        },
    }


def _path_domain(path: str) -> str:
    return "backlog" if _path_is_within(path, BACKLOG_ROOT_DIRECTORY) else "project_files"


def _head(worktree: Path) -> str:
    return _git(worktree, "rev-parse", "HEAD").stdout.strip()


def _branch(worktree: Path) -> str:
    return _git(worktree, "branch", "--show-current").stdout.strip()


def _discard_incomplete_worktree(repository: Path, worktree: Path, branch: str) -> None:
    _git(repository, "worktree", "remove", "--force", str(worktree), check=False)
    _git(repository, "branch", "-D", branch, check=False)


def _create_isolated_worktree(repository: Path, worktree: Path, branch: str, base: str) -> str | None:
    created = _git(
        repository,
        "worktree",
        "add",
        "--no-checkout",
        "-b",
        branch,
        str(worktree),
        base,
        check=False,
    )
    if created.returncode != SUCCESS:
        return "git_worktree_create_failed"

    sparse_checkout = _git(
        worktree,
        "sparse-checkout",
        "set",
        "--no-cone",
        *ISOLATED_SPARSE_CHECKOUT_PATTERNS,
        check=False,
    )
    if sparse_checkout.returncode != SUCCESS:
        _discard_incomplete_worktree(repository, worktree, branch)
        return "sparse_checkout_configure_failed"

    populated = _git(worktree, "reset", "--hard", "HEAD", check=False)
    if populated.returncode != SUCCESS:
        _discard_incomplete_worktree(repository, worktree, branch)
        return "sparse_checkout_populate_failed"
    return None


def _bounded_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()[:MAX_IDENTIFIER_LENGTH]


def _valid_blocker_reference(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and value == value.strip()
        and "\n" not in value
        and "\r" not in value
        and len(value) <= MAX_IDENTIFIER_LENGTH
    )


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _normalize_repository_path(
    repository: Path,
    value: str,
    case_sensitive: bool,
) -> str:
    stripped = value.strip()
    if not stripped:
        raise _ScopeError("Scope paths cannot be empty.", value, "provide a repository-relative path")
    if any(character in stripped for character in "*?["):
        raise _ScopeError(
            "Wildcard scopes are not supported.",
            stripped,
            "use --tree <path> or --all-files",
        )
    candidate = Path(os.path.normpath(str(Path(stripped))))
    if candidate.is_absolute():
        repository_parts = repository.parts
        candidate_parts = candidate.parts
        if case_sensitive:
            contained = candidate_parts[: len(repository_parts)] == repository_parts
        else:
            contained = tuple(part.casefold() for part in candidate_parts[: len(repository_parts)]) == tuple(
                part.casefold() for part in repository_parts
            )
        if not contained:
            raise _ScopeError(
                "Scope paths must remain inside the repository.",
                stripped,
                "provide a repository-relative path",
            )
        candidate = Path(*candidate_parts[len(repository_parts):])
    normalized = candidate.as_posix()
    if normalized == ".." or normalized.startswith("../"):
        raise _ScopeError(
            "Scope paths must remain inside the repository.",
            stripped,
            "provide a repository-relative path",
        )
    normalized = normalized if case_sensitive else normalized.casefold()
    if _path_is_within(normalized, WORKTREE_ROOT_DIRECTORY) or _path_is_within(
        normalized,
        CLAIM_STATE_DIRECTORY,
    ):
        raise _ScopeError(
            "Ignored operational state is outside file ownership domains.",
            normalized,
            "claim the project source path or an exclusive resource instead",
            "operational_path_not_claimable",
        )
    return normalized.rstrip("/") or "."


def _empty_scope() -> dict[str, Any]:
    return {
        "files": [],
        "trees": [],
        "project_files": False,
        "backlog": False,
        "all_files": False,
        "file_domain": "none",
        "resources": [],
        "scope_reason": None,
        "work_item_id": None,
        "activity": None,
    }


def _scope_from_args(args: argparse.Namespace, repository: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    scope = _empty_scope()
    warnings: list[dict[str, str]] = []
    compatibility = bool(getattr(args, "compat_file_directories", False))
    raw_files = list(getattr(args, "file", []))
    raw_trees = list(getattr(args, "tree", []))
    case_sensitive = (
        _filesystem_is_case_sensitive(_primary_worktree(repository))
        if raw_files or raw_trees
        else True
    )

    for raw_file in raw_files:
        normalized = _normalize_repository_path(
            repository,
            raw_file,
            case_sensitive,
        )
        if normalized == ".":
            raise _ScopeError(
                "Repository-wide ownership cannot be requested through --file.",
                raw_file,
                "use --all-files with --scope-reason",
            )
        candidate = repository / normalized
        if not candidate.is_symlink() and candidate.is_dir():
            if not compatibility:
                raise _ScopeError(
                    "Existing directories cannot be requested through --file.",
                    normalized,
                    "use --tree <path> with --scope-reason",
                )
            scope["trees"].append(normalized)
            warnings.append(
                {
                    "code": "legacy_file_directory_scope",
                    "message": f"Converted --file {normalized} to an explicit tree scope.",
                }
            )
        else:
            scope["files"].append(normalized)

    for raw_tree in raw_trees:
        normalized = _normalize_repository_path(
            repository,
            raw_tree,
            case_sensitive,
        )
        if normalized == ".":
            raise _ScopeError(
                "Repository root cannot be requested as a tree.",
                raw_tree,
                "use --all-files with --scope-reason",
            )
        candidate = repository / normalized
        if not candidate.is_symlink() and candidate.is_file():
            raise _ScopeError(
                "Existing files cannot be requested through --tree.",
                normalized,
                "use --file <path>",
            )
        scope["trees"].append(normalized)

    scope["files"] = _deduplicate(scope["files"])
    scope["trees"] = _deduplicate(scope["trees"])
    scope["resources"] = _deduplicate(
        value.strip() for value in getattr(args, "resource", []) if value.strip()
    )
    scope["project_files"] = bool(getattr(args, "project_files", False))
    scope["backlog"] = bool(getattr(args, "backlog", False))
    scope["all_files"] = bool(getattr(args, "all_files", False))

    selected_broad_domains = [
        domain
        for domain in ("project_files", "backlog", "all_files")
        if scope[domain]
    ]
    if len(selected_broad_domains) > 1:
        raise _ScopeError(
            "Broad file domains are mutually exclusive.",
            ", ".join(selected_broad_domains),
            "select exactly one of --project-files, --backlog, or --all-files",
            "multiple_broad_file_domains",
        )

    path_domains = {_path_domain(path) for _kind, path in _path_scopes(scope, include_broad=False)}
    if len(path_domains) > 1:
        raise _ScopeError(
            "One claim cannot mix project and backlog paths.",
            ", ".join(sorted(path_domains)),
            "use separate project and backlog claims",
            "mixed_file_domains",
        )
    broad_domain = selected_broad_domains[0] if selected_broad_domains else None
    path_domain = next(iter(path_domains), None)
    if broad_domain in {"project_files", "backlog"} and path_domain and broad_domain != path_domain:
        raise _ScopeError(
            "Explicit paths must belong to the selected broad file domain.",
            path_domain,
            f"use only {broad_domain.replace('_', '-')} paths or a separate claim",
            "mixed_file_domains",
        )
    scope["file_domain"] = broad_domain or path_domain or "none"
    if path_domain == "backlog" and not scope["backlog"]:
        warnings.append(
            {
                "code": "compat_backlog_path",
                "message": "Classified explicit backlog paths as backlog-domain ownership.",
            }
        )

    reason = getattr(args, "scope_reason", None)
    if reason is not None:
        reason = reason.strip()
        if not reason or "\n" in reason or "\r" in reason or len(reason) > MAX_SCOPE_REASON_LENGTH:
            raise _ScopeError(
                f"Scope reasons must contain 1 to {MAX_SCOPE_REASON_LENGTH} single-line characters.",
                reason,
                "provide a short coordination-only --scope-reason",
            )
    if (
        scope["trees"]
        or scope["project_files"]
        or scope["backlog"]
        or scope["all_files"]
    ) and not reason:
        raise _ScopeError(
            "Broad tree and file-domain scopes require a reason.",
            ", ".join(scope["trees"]) or scope["file_domain"],
            "add --scope-reason with bounded coordination-only text",
            "scope_reason_required",
        )
    scope["scope_reason"] = reason
    work_item_id = getattr(args, "work_item_id", None)
    activity = getattr(args, "activity", None)
    if (work_item_id is None) != (activity is None):
        missing = "activity" if activity is None else "work_item_id"
        raise _WorkItemError(
            "Work-item acquisition requires both work_item_id and activity.",
            missing,
            "incomplete_work_item_scope",
        )
    if work_item_id is not None:
        if (
            not isinstance(work_item_id, str)
            or not work_item_id
            or work_item_id != work_item_id.strip()
            or "\n" in work_item_id
            or "\r" in work_item_id
            or len(work_item_id) > MAX_IDENTIFIER_LENGTH
        ):
            raise _WorkItemError(
                "work_item_id must be a canonical non-empty single-line value of at most 200 characters.",
                "work_item_id",
                "invalid_work_item_id",
            )
        if activity not in {"work", "update"}:
            raise _WorkItemError(
                "activity must be exactly work or update.",
                "activity",
                "invalid_activity",
            )
        if (
            scope["files"]
            or scope["trees"]
            or scope["project_files"]
            or scope["backlog"]
            or scope["all_files"]
            or scope["resources"]
        ):
            raise _WorkItemError(
                "A work-item claim cannot combine path or resource scope.",
                "work_item_id",
                "mixed_work_item_and_operational_scope",
            )
        scope["work_item_id"] = work_item_id
        scope["activity"] = activity
    return scope, warnings


def _claim_scope(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "files": [str(value) for value in claim.get("files", [])],
        "trees": [str(value) for value in claim.get("trees", [])],
        "project_files": bool(claim.get("project_files", False)),
        "backlog": bool(claim.get("backlog", False)),
        "all_files": bool(claim.get("all_files", False)),
        "file_domain": str(claim.get("file_domain") or _legacy_file_domain(claim)),
        "resources": [str(value) for value in claim.get("resources", [])],
        "scope_reasons": dict(claim.get("scope_reasons", {})),
        "work_item_id": claim.get("work_item_id"),
        "activity": claim.get("activity"),
    }


def _legacy_file_domain(claim: dict[str, Any]) -> str:
    if claim.get("all_files"):
        return "all_files"
    domains = {
        _path_domain(str(path))
        for path in [*claim.get("files", []), *claim.get("trees", [])]
    }
    if len(domains) == 1:
        return next(iter(domains))
    if len(domains) > 1:
        return "legacy_mixed"
    return "none"


def _claim_for_output(
    claim: dict[str, Any],
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    rendered = dict(claim)
    if "file_domain" not in claim:
        rendered["file_domain"] = _legacy_file_domain(claim)
        rendered["project_files"] = False
        rendered["backlog"] = False
        rendered["compatibility"] = {"legacy_registry_claim": True}
    deadline = claim.get("deadline")
    if isinstance(deadline, dict) and evaluated_at is not None:
        rendered["deadline_status"] = _deadline_status(deadline, evaluated_at)
    return rendered


def _path_is_within(path: str, tree: str) -> bool:
    return path == tree or path.startswith(tree + "/")


def _filesystem_is_case_sensitive(directory: Path) -> bool:
    entries = set(os.listdir(directory))
    for entry in entries:
        variant = _single_character_case_variant(entry)
        if variant is None or variant in entries:
            continue
        return not os.path.lexists(directory / variant)
    raise OSError(f"Unable to establish filesystem case sensitivity for {directory}")


def _single_character_case_variant(value: str) -> str | None:
    for index, character in enumerate(value):
        if "a" <= character <= "z":
            return f"{value[:index]}{character.upper()}{value[index + 1:]}"
        if "A" <= character <= "Z":
            return f"{value[:index]}{character.lower()}{value[index + 1:]}"
    return None


def _claim_scope_for_comparison(
    claim: dict[str, Any],
    repository: Path,
) -> dict[str, Any]:
    raw_files = claim.get("files", [])
    raw_trees = claim.get("trees", [])
    try:
        if not isinstance(raw_files, list) or not all(
            isinstance(path, str) for path in raw_files
        ):
            raise _ScopeError(
                "Stored file scopes must be repository-relative path strings.",
                str(raw_files),
                "release or reconcile the invalid legacy claim",
                "invalid_stored_scope",
            )
        if not isinstance(raw_trees, list) or not all(
            isinstance(path, str) for path in raw_trees
        ):
            raise _ScopeError(
                "Stored tree scopes must be repository-relative path strings.",
                str(raw_trees),
                "release or reconcile the invalid legacy claim",
                "invalid_stored_scope",
            )
        scope = _claim_scope(claim)
        if not raw_files and not raw_trees:
            return scope
        case_sensitive = _filesystem_is_case_sensitive(_primary_worktree(repository))
        scope["files"] = _deduplicate(
            _normalize_repository_path(repository, path, case_sensitive)
            for path in raw_files
        )
        scope["trees"] = _deduplicate(
            _normalize_repository_path(repository, path, case_sensitive)
            for path in raw_trees
        )
        if "." in scope["files"] or "." in scope["trees"]:
            raise _ScopeError(
                "Stored exact path scopes cannot represent the repository root.",
                ".",
                "release or reconcile the invalid legacy claim",
                "invalid_stored_scope",
            )
        if "file_domain" not in claim:
            scope["file_domain"] = _legacy_file_domain(scope)
    except (OSError, _ScopeError):
        scope = _empty_scope()
        raw_resources = claim.get("resources", [])
        if isinstance(raw_resources, list):
            scope["resources"] = [str(resource) for resource in raw_resources]
        scope["files"] = []
        scope["trees"] = []
        scope["project_files"] = False
        scope["backlog"] = False
        scope["all_files"] = True
        scope["file_domain"] = "all_files"
        scope["work_item_id"] = claim.get("work_item_id")
        scope["activity"] = claim.get("activity")
    return scope


def _path_scope_overlap(
    requested_kind: str,
    requested_path: str,
    claimed_kind: str,
    claimed_path: str,
) -> bool:
    if "all_files" in {requested_kind, claimed_kind}:
        return True
    if requested_kind == "project_files":
        return claimed_kind == "project_files" or _path_domain(claimed_path) == "project_files"
    if claimed_kind == "project_files":
        return requested_kind == "project_files" or _path_domain(requested_path) == "project_files"
    if requested_kind == "backlog":
        return claimed_kind == "backlog" or _path_domain(claimed_path) == "backlog"
    if claimed_kind == "backlog":
        return requested_kind == "backlog" or _path_domain(requested_path) == "backlog"
    if requested_kind == "file" and claimed_kind == "file":
        return requested_path == claimed_path
    if requested_kind == "tree" and claimed_kind == "tree":
        return _path_is_within(requested_path, claimed_path) or _path_is_within(claimed_path, requested_path)
    if requested_kind == "tree":
        return _path_is_within(claimed_path, requested_path)
    return _path_is_within(requested_path, claimed_path)


def _path_scopes(scope: dict[str, Any], include_broad: bool = True) -> list[tuple[str, str]]:
    values = [("file", value) for value in scope.get("files", [])]
    values.extend(("tree", value) for value in scope.get("trees", []))
    if include_broad:
        if scope.get("project_files"):
            values.append(("project_files", "."))
        if scope.get("backlog"):
            values.append(("backlog", BACKLOG_ROOT_DIRECTORY))
        if scope.get("all_files"):
            values.append(("all_files", "."))
    return values


def _scope_requires_primary_worktree(scope: dict[str, Any]) -> bool:
    return bool(scope.get("project_files")) or scope.get("file_domain") in {
        "backlog",
        "all_files",
    }


def _scope_file_domain(scope: dict[str, Any]) -> str:
    explicit = str(scope.get("file_domain") or "")
    if explicit:
        return explicit
    if scope.get("all_files"):
        return "all_files"
    if scope.get("project_files"):
        return "project_files"
    if scope.get("backlog"):
        return "backlog"
    domains = {
        _path_domain(str(path))
        for path in [*scope.get("files", []), *scope.get("trees", [])]
    }
    if len(domains) == 1:
        return next(iter(domains))
    return "legacy_mixed" if domains else "none"


def _scope_is_resource_only(scope: dict[str, Any]) -> bool:
    return _scope_file_domain(scope) == "none" and bool(scope.get("resources"))


def _overlap_details(
    requested: dict[str, Any],
    claimed: dict[str, Any],
) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    requested_work_item_id = requested.get("work_item_id")
    claimed_work_item_id = claimed.get("work_item_id")
    if requested_work_item_id and requested_work_item_id == claimed_work_item_id:
        details.append(
            {
                "scope_kind": "work_item",
                "requested_kind": "work_item",
                "requested": str(requested_work_item_id),
                "claimed_kind": "work_item",
                "claimed": str(claimed_work_item_id),
            }
        )
    for requested_kind, requested_path in _path_scopes(requested):
        for claimed_kind, claimed_path in _path_scopes(claimed):
            if _path_scope_overlap(
                requested_kind,
                requested_path,
                claimed_kind,
                claimed_path,
            ):
                details.append(
                    {
                        "scope_kind": "path",
                        "requested_kind": requested_kind,
                        "requested": requested_path,
                        "claimed_kind": claimed_kind,
                        "claimed": claimed_path,
                    }
                )
    claimed_resources = set(claimed.get("resources", []))
    for resource in requested.get("resources", []):
        if resource in claimed_resources:
            details.append(
                {
                    "scope_kind": "resource",
                    "requested_kind": "resource",
                    "requested": resource,
                    "claimed_kind": "resource",
                    "claimed": resource,
                }
            )
    return details


def _conflicts(
    claims: list[dict[str, Any]],
    requested: dict[str, Any],
    repository: Path,
    excluded_claim_id: str | None = None,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for claim in claims:
        if claim.get("claim_id") == excluded_claim_id:
            continue
        details = _overlap_details(
            requested,
            _claim_scope_for_comparison(claim, repository),
        )
        if details:
            conflicts.append({"claim_id": claim["claim_id"], "overlaps": details})
    return conflicts


def _scope_reasons(scope: dict[str, Any]) -> dict[str, str]:
    reason = scope.get("scope_reason")
    if not reason:
        return {}
    reasons = {f"tree:{path}": reason for path in scope.get("trees", [])}
    if scope.get("project_files"):
        reasons["project_files:."] = reason
    if scope.get("backlog"):
        reasons["backlog:backlog"] = reason
    if scope.get("all_files"):
        reasons["all_files:."] = reason
    return reasons


def _owned_and_added_scope(
    claim: dict[str, Any],
    requested: dict[str, Any],
    repository: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    current = _claim_scope_for_comparison(claim, repository)
    added = _empty_scope()
    owned = _empty_scope()

    current_domain = current["file_domain"]
    requested_domain = requested["file_domain"]
    if current_domain == "legacy_mixed" and requested_domain != "none":
        raise _ScopeError(
            "An active legacy claim with mixed paths cannot be extended with file scope.",
            "legacy_mixed",
            "finish or hand off the legacy claim before acquiring one explicit file domain",
            "legacy_mixed_file_domains",
        )
    if current_domain != "none" and requested_domain != "none" and current_domain != requested_domain:
        raise _ScopeError(
            "An active claim cannot cross file domains.",
            f"{current_domain}, {requested_domain}",
            "use a separate claim for the other file domain",
            "mixed_file_domains",
        )

    for file_path in requested["files"]:
        target = owned if (
            current["all_files"]
            or current["project_files"] and _path_domain(file_path) == "project_files"
            or current["backlog"] and _path_domain(file_path) == "backlog"
            or file_path in current["files"]
            or any(_path_is_within(file_path, tree) for tree in current["trees"])
        ) else added
        target["files"].append(file_path)
    for tree_path in requested["trees"]:
        target = owned if (
            current["all_files"]
            or current["project_files"] and _path_domain(tree_path) == "project_files"
            or current["backlog"] and _path_domain(tree_path) == "backlog"
            or any(_path_is_within(tree_path, tree) for tree in current["trees"])
        ) else added
        target["trees"].append(tree_path)
    if requested["project_files"]:
        (owned if current["project_files"] or current["all_files"] else added)["project_files"] = True
    if requested["backlog"]:
        (owned if current["backlog"] or current["all_files"] else added)["backlog"] = True
    if requested["all_files"]:
        (owned if current["all_files"] else added)["all_files"] = True
    current_resources = set(current["resources"])
    for resource in requested["resources"]:
        (owned if resource in current_resources else added)["resources"].append(resource)

    added["scope_reason"] = requested.get("scope_reason")
    owned["scope_reason"] = requested.get("scope_reason")
    added["file_domain"] = requested_domain if _scope_has_file_values(added) else "none"
    owned["file_domain"] = requested_domain if _scope_has_file_values(owned) else "none"
    return owned, added


def _scope_has_file_values(scope: dict[str, Any]) -> bool:
    return bool(
        scope["files"]
        or scope["trees"]
        or scope["project_files"]
        or scope["backlog"]
        or scope["all_files"]
    )


def _scope_has_values(scope: dict[str, Any]) -> bool:
    return bool(
        _scope_has_file_values(scope)
        or scope["resources"]
        or scope.get("work_item_id")
    )


def _apply_scope(claim: dict[str, Any], added: dict[str, Any]) -> None:
    assign_file_domain = (
        added["file_domain"] != "none"
        and (
            claim.get("file_domain") == "none"
            or "file_domain" not in claim and _legacy_file_domain(claim) == "none"
        )
    )
    claim["files"] = _deduplicate([*claim.get("files", []), *added["files"]])
    claim["trees"] = _deduplicate([*claim.get("trees", []), *added["trees"]])
    claim["project_files"] = bool(claim.get("project_files", False) or added["project_files"])
    claim["backlog"] = bool(claim.get("backlog", False) or added["backlog"])
    claim["all_files"] = bool(claim.get("all_files", False) or added["all_files"])
    if assign_file_domain:
        claim["file_domain"] = added["file_domain"]
    claim["resources"] = _deduplicate([*claim.get("resources", []), *added["resources"]])
    reasons = dict(claim.get("scope_reasons", {}))
    reasons.update(_scope_reasons(added))
    claim["scope_reasons"] = reasons


def _worktree_identifier(claim: dict[str, Any]) -> str | None:
    topology = _checkout_topology(claim)
    if topology == "primary":
        return "primary"
    branch = claim.get("branch")
    if branch:
        return str(branch)
    return "linked" if topology == "linked" else None


def _event(
    action: str,
    outcome: str,
    args: argparse.Namespace,
    claim: dict[str, Any] | None = None,
    requested_scope: dict[str, Any] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    event = {
        "schema_version": EVENT_SCHEMA_VERSION,
        "event_id": str(uuid4()),
        "timestamp": _timestamp(),
        "action": action,
        "outcome": outcome,
        "claim_id": _bounded_identifier(getattr(args, "claim_id", None)),
        "incarnation_id": claim.get("incarnation_id") if claim else None,
        "root_task_id": _bounded_identifier(
            claim.get("root_task_id") if claim else getattr(args, "root_task_id", None)
        ),
        "parent_claim_id": _bounded_identifier(
            claim.get("parent_claim_id") if claim else getattr(args, "parent_claim_id", None)
        ),
        "agent": _bounded_identifier(claim.get("agent") if claim else getattr(args, "agent", None)),
        "mode": claim.get("mode") if claim else None,
        "scopes": _claim_scope(claim) if claim else None,
        "requested_scopes": requested_scope,
        "conflicting_claim_ids": [item["claim_id"] for item in conflicts or []],
        "overlaps": [
            {"claim_id": item["claim_id"], **overlap}
            for item in conflicts or []
            for overlap in item["overlaps"]
        ],
        "branch": claim.get("branch") if claim else None,
        "checkout_topology": _checkout_topology(claim) if claim else None,
        "worktree_id": _worktree_identifier(claim) if claim else None,
        "baseline_commit": claim.get("baseline_commit") if claim else None,
        "deadline": claim.get("deadline") if claim else None,
        "work_item_id": (
            claim.get("work_item_id")
            if claim
            else _bounded_identifier(getattr(args, "work_item_id", None))
        ),
        "activity": (
            claim.get("activity") if claim else getattr(args, "activity", None)
        ),
        "resulting_commit": extra.pop("resulting_commit", None),
        "command_warnings": extra.pop("command_warnings", []),
        "journal_warnings": [],
    }
    event.update(extra)
    return event


def _canonical_outcome(outcome: str, shared_checkout_claimed: bool = False) -> str:
    if outcome == "PRIMARY_REQUIRED" and shared_checkout_claimed:
        return "SHARED_CHECKOUT_RELEASE_REQUIRED"
    return LEGACY_OUTCOME_ALIASES.get(outcome, outcome)


def _normalized_event_outcomes(
    events: Sequence[dict[str, Any]],
) -> tuple[list[str], list[dict[str, str]]]:
    normalized: list[str] = []
    gaps: list[dict[str, str]] = []
    for event in sorted(events, key=_event_sort_key):
        event_id = str(event.get("event_id") or "")
        raw_outcome = str(event.get("outcome"))
        if raw_outcome == "PRIMARY_REQUIRED":
            shared_checkout_claimed = event.get("shared_checkout_claimed")
            if isinstance(shared_checkout_claimed, bool):
                outcome = _canonical_outcome(raw_outcome, shared_checkout_claimed)
            else:
                outcome = raw_outcome
                gaps.append(
                    {
                        "source": event_id,
                        "detail": (
                            "legacy PRIMARY_REQUIRED lacks deterministic "
                            "shared-checkout ownership evidence"
                        ),
                    }
                )
        else:
            outcome = _canonical_outcome(raw_outcome)
        normalized.append(outcome)
    return normalized, gaps


def _append_event(common_directory: Path, event: dict[str, Any]) -> Path:
    if os.environ.get("AGENT_CLAIM_TEST_FAIL_JOURNAL_WRITE") == "1":
        raise OSError("simulated journal write failure")
    _root, hot_directory, _archive, _journal = _journal_paths(common_directory)
    hot_directory.mkdir(parents=True, exist_ok=True)
    day = _parse_timestamp(event["timestamp"]).date().isoformat()
    path = hot_directory / f"{day}.jsonl"
    encoded = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path


def _print_result(
    outcome: str,
    *,
    canonical_outcome: str | None = None,
    **details: Any,
) -> None:
    result_outcome = canonical_outcome or _canonical_outcome(outcome)
    result = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "outcome": result_outcome,
        **details,
    }
    if result_outcome != outcome:
        result["legacy_outcome"] = outcome
    _emit_result(result)


def _emit_result(result: dict[str, Any]) -> None:
    sink = _RESULT_SINK.get()
    if sink is not None:
        sink.append(result)
        return
    print(json.dumps(result, indent=2, sort_keys=True))


def _journaled_result(
    code: int,
    common_directory: Path,
    event: dict[str, Any],
    output_warnings: list[dict[str, str]] | None = None,
    canonical_outcome: str | None = None,
    **details: Any,
) -> int:
    warnings = list(output_warnings or [])
    try:
        path = _append_event(common_directory, event)
        journal = {"event_id": event["event_id"], "path": str(path)}
    except OSError as error:
        warning = {"code": "journal_write_failed", "message": str(error)}
        warnings.append(warning)
        journal = {"event_id": event["event_id"], "persisted": False}
    if warnings:
        details["warnings"] = warnings
    _print_result(
        event["outcome"],
        canonical_outcome=canonical_outcome,
        journal=journal,
        **details,
    )
    return code


def _invalid_scope_result(
    common_directory: Path,
    action: str,
    args: argparse.Namespace,
    error: _ScopeError,
) -> int:
    rejection = {
        "message": str(error),
        "offending_scope": error.offending_scope,
        "replacement": error.replacement,
        "reason": error.reason,
    }
    event = _event(
        action,
        "INVALID_SCOPE",
        args,
        rejection=rejection,
    )
    return _journaled_result(
        ERROR,
        common_directory,
        event,
        message=str(error),
        offending_scope=error.offending_scope,
        replacement=error.replacement,
        rejection=event["rejection"],
    )


def _invalid_deadline_result(
    common_directory: Path,
    action: str,
    args: argparse.Namespace,
    error: _DeadlineError,
    claim: dict[str, Any] | None = None,
) -> int:
    outcome = "INVALID_DEADLINE_EXTENSION" if action == "extend-deadline" else "INVALID_DEADLINE_POLICY"
    event = _event(
        action,
        outcome,
        args,
        claim=claim,
        rejection={
            "message": str(error),
            "field": error.field,
            "reason": error.reason,
        },
    )
    return _journaled_result(
        ERROR,
        common_directory,
        event,
        message=str(error),
        field=error.field,
        rejection=event["rejection"],
    )


def _invalid_work_item_result(
    common_directory: Path,
    action: str,
    args: argparse.Namespace,
    error: _WorkItemError,
    claim: dict[str, Any] | None = None,
) -> int:
    outcome = (
        "INVALID_WORK_ITEM_RELEASE"
        if action == "release"
        else "INVALID_WORK_ITEM_SCOPE"
    )
    rejection = {
        "message": str(error),
        "field": error.field,
        "reason": error.reason,
    }
    event = _event(
        action,
        outcome,
        args,
        claim=claim,
        rejection=rejection,
    )
    return _journaled_result(
        ERROR,
        common_directory,
        event,
        message=str(error),
        field=error.field,
        rejection=rejection,
    )


def _primary_required_result(
    common_directory: Path,
    action: str,
    args: argparse.Namespace,
    requested_scope: dict[str, Any],
    scope_warnings: list[dict[str, str]],
    claim: dict[str, Any] | None = None,
    **details: Any,
) -> int:
    if requested_scope.get("project_files"):
        reason = "project_files_requires_primary_worktree"
        message = "Project-files scope is available only from the primary worktree."
    else:
        reason = "backlog_requires_primary_worktree"
        message = "Backlog scope is available only from the primary worktree."
    event = _event(
        action,
        "PRIMARY_REQUIRED",
        args,
        claim=claim,
        requested_scope=requested_scope,
        reason=reason,
        shared_checkout_claimed=False,
        command_warnings=scope_warnings,
        **details,
    )
    return _journaled_result(
        COORDINATION_REQUIRED_EXIT_CODE,
        common_directory,
        event,
        scope_warnings,
        canonical_outcome=_canonical_outcome(
            event["outcome"],
            shared_checkout_claimed=False,
        ),
        reason=reason,
        message=message,
        requested_scopes=requested_scope,
        **details,
    )


def _invalid_identifier_result(common_directory: Path, args: argparse.Namespace) -> int:
    message = "claim_id must be one portable path component containing only letters, digits, dots, underscores, or hyphens."
    event = _event(
        "acquire",
        "INVALID_IDENTIFIER",
        args,
        field="claim_id",
        reason="claim_id_not_portable_path_component",
    )
    return _journaled_result(
        ERROR,
        common_directory,
        event,
        field="claim_id",
        message=message,
    )


def _invalid_worktree_path_result(
    common_directory: Path,
    args: argparse.Namespace,
    expected_worktree: Path,
    provided_worktree: Path,
) -> int:
    event = _event(
        "acquire",
        "INVALID_WORKTREE_PATH",
        args,
        reason="worktree_path_not_canonical",
    )
    return _journaled_result(
        ERROR,
        common_directory,
        event,
        expected_worktree=str(expected_worktree),
        provided_worktree=str(provided_worktree),
        message="The worktree path must match the canonical target under the primary worktree.",
    )


def _worktree_root_not_ignored_result(
    common_directory: Path,
    args: argparse.Namespace,
    worktree_root: Path,
) -> int:
    event = _event(
        "acquire",
        "WORKTREE_ROOT_NOT_IGNORED",
        args,
        reason="canonical_worktree_root_not_ignored",
    )
    return _journaled_result(
        ERROR,
        common_directory,
        event,
        worktree_root=str(worktree_root),
        required_ignore_pattern=WORKTREE_IGNORE_PATTERN,
        message="Ignore the canonical worktree root before creating an isolated worktree.",
    )


def _acquire(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository, "acquire", args.claim_id) as (registry_path, data, registry_file):
        common_directory = registry_path.parent
        try:
            requested_scope, scope_warnings = _scope_from_args(args, repository)
        except _ScopeError as error:
            return _invalid_scope_result(common_directory, "acquire", args, error)
        except _WorkItemError as error:
            return _invalid_work_item_result(
                common_directory,
                "acquire",
                args,
                error,
            )
        if not _scope_has_values(requested_scope):
            error = _ScopeError(
                "Acquisition requires a work item, file, tree, broad file domain, or named resource.",
                "none",
                "provide an Event Contract scope",
                "missing_scope",
            )
            return _invalid_scope_result(common_directory, "acquire", args, error)
        try:
            deadline_request = _deadline_request_from_args(
                args,
                requested_scope["resources"],
                repository,
            )
        except _DeadlineError as error:
            return _invalid_deadline_result(common_directory, "acquire", args, error)
        if not _claim_id_is_safe_worktree_component(args.claim_id):
            return _invalid_identifier_result(common_directory, args)

        claims: list[dict[str, Any]] = data["claims"]
        if any(claim.get("claim_id") == args.claim_id for claim in claims):
            event = _event("acquire", "CLAIM_ID_EXISTS", args, requested_scope=requested_scope)
            return _journaled_result(ERROR, common_directory, event, claim_id=args.claim_id)

        conflicts = _conflicts(claims, requested_scope, repository)
        if conflicts:
            event = _event(
                "acquire",
                "WAIT",
                args,
                requested_scope=requested_scope,
                conflicts=conflicts,
                command_warnings=scope_warnings,
            )
            return _journaled_result(
                COORDINATION_REQUIRED_EXIT_CODE,
                common_directory,
                event,
                scope_warnings,
                conflicting_claim_ids=[item["claim_id"] for item in conflicts],
                overlaps=event["overlaps"],
            )

        requires_primary = _scope_requires_primary_worktree(requested_scope)
        if requires_primary:
            primary_worktree = _primary_worktree(repository)
            caller_is_primary = repository == primary_worktree
            if not caller_is_primary:
                return _primary_required_result(
                    common_directory,
                    "acquire",
                    args,
                    requested_scope,
                    scope_warnings,
                    active_claim_count=len(claims),
                )

        if args.branch and not requires_primary:
            worktree_root = _canonical_worktree_root(repository)
            target_worktree = _canonical_worktree(repository, args.claim_id)
            if args.worktree_path:
                provided_worktree = Path(args.worktree_path).resolve()
                if provided_worktree != target_worktree:
                    return _invalid_worktree_path_result(
                        common_directory,
                        args,
                        target_worktree,
                        provided_worktree,
                    )
            if not _worktree_root_is_ignored(repository):
                return _worktree_root_not_ignored_result(common_directory, args, worktree_root)
            failure_reason = _create_isolated_worktree(
                repository,
                target_worktree,
                args.branch,
                args.base,
            )
            if failure_reason is not None:
                event = _event(
                    "acquire",
                    "WORKTREE_CREATE_FAILED",
                    args,
                    requested_scope=requested_scope,
                    reason=failure_reason,
                )
                return _journaled_result(ERROR, common_directory, event, message="Git worktree creation failed.")
            mode = "isolated"
            outcome = "ISOLATE"
        else:
            target_worktree = repository
            mode = "primary"
            outcome = "PRIMARY"

        now = _timestamp()
        deadline = (
            _deadline_from_request(deadline_request, now)
            if deadline_request is not None
            else None
        )
        claim = {
            "agent": args.agent,
            "backlog": requested_scope["backlog"],
            "all_files": requested_scope["all_files"],
            "baseline_commit": _head(target_worktree),
            "branch": _branch(target_worktree),
            "checkout_topology": (
                "primary"
                if target_worktree == _primary_worktree(repository)
                else "linked"
            ),
            "claim_id": args.claim_id,
            "claimed_at": now,
            "incarnation_id": str(uuid4()),
            "files": requested_scope["files"],
            "file_domain": requested_scope["file_domain"],
            "heartbeat": now,
            "mode": mode,
            "parent_claim_id": args.parent_claim_id,
            "project_files": requested_scope["project_files"],
            "resources": requested_scope["resources"],
            "root_task_id": args.root_task_id,
            "scope_reasons": _scope_reasons(requested_scope),
            "task": args.task,
            "trees": requested_scope["trees"],
            "worktree": str(target_worktree),
        }
        if requested_scope["work_item_id"] is not None:
            claim["acquisition_outcome"] = _canonical_outcome(outcome)
            claim["work_item_id"] = requested_scope["work_item_id"]
            claim["activity"] = requested_scope["activity"]
        if deadline is not None:
            claim["deadline"] = deadline
        claims.append(claim)
        _write_registry(registry_file, data)
        event = _event(
            "acquire",
            outcome,
            args,
            claim=claim,
            requested_scope=requested_scope,
            command_warnings=scope_warnings,
        )
        return _journaled_result(
            SUCCESS,
            common_directory,
            event,
            scope_warnings,
            claim=claim,
            registry=str(registry_path),
            target={
                "mode": mode,
                "branch": claim["branch"],
                "checkout_topology": claim["checkout_topology"],
                "worktree": str(target_worktree),
            },
        )


def _extend(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository, "extend", args.claim_id) as (registry_path, data, registry_file):
        common_directory = registry_path.parent
        try:
            requested_scope, scope_warnings = _scope_from_args(args, repository)
        except _ScopeError as error:
            return _invalid_scope_result(common_directory, "extend", args, error)
        claims: list[dict[str, Any]] = data["claims"]
        claim = next((item for item in claims if item.get("claim_id") == args.claim_id), None)
        if claim is None:
            event = _event("extend", "CLAIM_NOT_FOUND", args, requested_scope=requested_scope)
            return _journaled_result(ERROR, common_directory, event, claim_id=args.claim_id)
        if claim.get("work_item_id") is not None and _scope_has_values(requested_scope):
            error = _WorkItemError(
                "A work-item claim cannot be extended with path or resource scope; acquire a separate operational claim.",
                "work_item_id",
                "work_item_operational_extension",
            )
            return _invalid_work_item_result(
                common_directory,
                "extend",
                args,
                error,
                claim,
            )
        if (
            _scope_is_resource_only(_claim_scope(claim))
            and requested_scope["file_domain"] in {"backlog", "all_files"}
        ):
            error = _ScopeError(
                "A resource-only claim cannot be extended into backlog ownership.",
                requested_scope["file_domain"],
                "acquire a separate backlog claim from the primary worktree",
                "resource_only_backlog_extension",
            )
            return _invalid_scope_result(common_directory, "extend", args, error)

        current_resources = [str(resource) for resource in claim.get("resources", [])]
        requested_resources = requested_scope["resources"]
        if requested_resources and current_resources and requested_resources != current_resources:
            error = _DeadlineError(
                "A claim that owns one named resource cannot add a second named resource.",
                "resource",
                "second_resource_not_supported",
            )
            return _invalid_deadline_result(common_directory, "extend", args, error, claim)
        try:
            deadline_request = _deadline_request_from_args(
                args,
                requested_resources,
                repository,
            )
        except _DeadlineError as error:
            return _invalid_deadline_result(common_directory, "extend", args, error, claim)
        if requested_resources and current_resources and not isinstance(claim.get("deadline"), dict):
            error = _DeadlineError(
                "The existing named resource has no complete timing evidence.",
                "deadline",
                "resource_timing_missing",
            )
            return _invalid_deadline_result(common_directory, "extend", args, error, claim)

        if claim.get("mode") == "isolated" and requested_scope.get("file_domain") in {
            "backlog",
            "all_files",
        }:
            return _primary_required_result(
                common_directory,
                "extend",
                args,
                requested_scope,
                scope_warnings,
                claim=claim,
            )

        try:
            already_owned, added = _owned_and_added_scope(
                claim,
                requested_scope,
                repository,
            )
        except _ScopeError as error:
            return _invalid_scope_result(common_directory, "extend", args, error)
        conflicts = (
            _conflicts(
                claims,
                added,
                repository,
                excluded_claim_id=args.claim_id,
            )
            if _scope_has_values(added)
            else []
        )
        if conflicts:
            event = _event(
                "extend",
                "WAIT",
                args,
                claim=claim,
                requested_scope=requested_scope,
                conflicts=conflicts,
                added_scope=added,
                already_owned_scope=already_owned,
                command_warnings=scope_warnings,
            )
            return _journaled_result(
                COORDINATION_REQUIRED_EXIT_CODE,
                common_directory,
                event,
                scope_warnings,
                conflicting_claim_ids=[item["claim_id"] for item in conflicts],
                overlaps=event["overlaps"],
                added_scope=added,
                already_owned_scope=already_owned,
            )

        if _checkout_topology(claim) == "linked" and _scope_requires_primary_worktree(added):
            return _primary_required_result(
                common_directory,
                "extend",
                args,
                requested_scope,
                scope_warnings,
                claim=claim,
                added_scope=added,
                already_owned_scope=already_owned,
            )

        if _scope_has_values(added):
            _apply_scope(claim, added)
            if added["resources"]:
                if deadline_request is None:
                    raise RuntimeError("Timed resource validation did not produce deadline evidence.")
                claim["deadline"] = _deadline_from_request(deadline_request, _timestamp())
            _write_registry(registry_file, data)
        event = _event(
            "extend",
            "EXTENDED",
            args,
            claim=claim,
            requested_scope=requested_scope,
            added_scope=added,
            already_owned_scope=already_owned,
            command_warnings=scope_warnings,
        )
        return _journaled_result(
            SUCCESS,
            common_directory,
            event,
            scope_warnings,
            claim=claim,
            added_scope=added,
            already_owned_scope=already_owned,
        )


def _heartbeat(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository, "heartbeat", args.claim_id) as (registry_path, data, registry_file):
        common_directory = registry_path.parent
        for claim in data["claims"]:
            if claim.get("claim_id") == args.claim_id:
                claim["heartbeat"] = _timestamp()
                _write_registry(registry_file, data)
                event = _event("heartbeat", "HEARTBEAT", args, claim=claim)
                return _journaled_result(SUCCESS, common_directory, event, claim=claim)
        event = _event("heartbeat", "CLAIM_NOT_FOUND", args)
        return _journaled_result(ERROR, common_directory, event, claim_id=args.claim_id)


def _extend_deadline(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository, "extend-deadline", args.claim_id) as (registry_path, data, registry_file):
        common_directory = registry_path.parent
        claim = next(
            (item for item in data["claims"] if item.get("claim_id") == args.claim_id),
            None,
        )
        if claim is None:
            event = _event("extend-deadline", "CLAIM_NOT_FOUND", args)
            return _journaled_result(ERROR, common_directory, event, claim_id=args.claim_id)
        deadline = claim.get("deadline")
        if not isinstance(deadline, dict):
            error = _DeadlineError(
                "claim has no configured resource deadline to extend.",
                "claim_id",
                "deadline_not_configured",
            )
            return _invalid_deadline_result(
                common_directory,
                "extend-deadline",
                args,
                error,
                claim,
            )

        requested = args.requested_hard_stop_duration_seconds
        current = deadline["requested_hard_stop_duration_seconds"]
        maximum = deadline["configured_maximum_duration_seconds"]
        evidence = args.extension_evidence.strip()
        if requested <= current:
            error = _DeadlineError(
                "extended hard stop must be greater than the current requested hard stop.",
                "requested_hard_stop_duration_seconds",
                "hard_stop_not_extended",
            )
            return _invalid_deadline_result(common_directory, "extend-deadline", args, error, claim)
        if requested > maximum:
            error = _DeadlineError(
                "extended hard stop must not exceed configured maximum.",
                "requested_hard_stop_duration_seconds",
                "hard_stop_exceeds_maximum",
            )
            return _invalid_deadline_result(common_directory, "extend-deadline", args, error, claim)
        if not evidence or len(evidence) > MAX_EXTENSION_EVIDENCE_LENGTH:
            error = _DeadlineError(
                f"extension evidence must contain 1 to {MAX_EXTENSION_EVIDENCE_LENGTH} characters.",
                "extension_evidence",
                "invalid_extension_evidence",
            )
            return _invalid_deadline_result(common_directory, "extend-deadline", args, error, claim)

        extended_at = _timestamp()
        acquired_at = _parse_timestamp(str(deadline["acquired_at"]))
        hard_stop_at = acquired_at + timedelta(seconds=requested)
        extension = {
            "extended_at": extended_at,
            "previous_requested_hard_stop_duration_seconds": current,
            "requested_hard_stop_duration_seconds": requested,
            "evidence": evidence,
        }
        deadline["requested_hard_stop_duration_seconds"] = requested
        deadline["hard_stop_at"] = _format_timestamp(hard_stop_at)
        deadline["cleanup_grace_ends_at"] = _format_timestamp(
            hard_stop_at + timedelta(seconds=deadline["cleanup_grace_seconds"])
        )
        deadline.setdefault("extensions", []).append(extension)
        _write_registry(registry_file, data)
        event = _event(
            "extend-deadline",
            "DEADLINE_EXTENDED",
            args,
            claim=claim,
            deadline_extension=extension,
        )
        return _journaled_result(
            SUCCESS,
            common_directory,
            event,
            claim=claim,
            deadline_extension=extension,
        )


def _release(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository, "release", args.claim_id) as (registry_path, data, registry_file):
        common_directory = registry_path.parent
        claims: list[dict[str, Any]] = data["claims"]
        for index, claim in enumerate(claims):
            if claim.get("claim_id") != args.claim_id:
                continue
            work_item_id = claim.get("work_item_id")
            if work_item_id is not None:
                try:
                    disposition = args.disposition
                    blocker_reference = args.blocker_reference
                    if disposition not in {"done", "blocked", "handoff"}:
                        raise _WorkItemError(
                            "Work-item release requires disposition done, blocked, or handoff.",
                            "disposition",
                            (
                                "disposition_required"
                                if disposition is None
                                else "invalid_disposition"
                            ),
                        )
                    if disposition == "blocked":
                        if (
                            blocker_reference is not None
                            and not _valid_blocker_reference(blocker_reference)
                        ):
                            raise _WorkItemError(
                                "blocker_reference must be a canonical non-empty single-line value of at most 200 characters.",
                                "blocker_reference",
                                "invalid_blocker_reference",
                            )
                    elif blocker_reference is not None:
                        raise _WorkItemError(
                            "blocker_reference is allowed only for blocked disposition.",
                            "blocker_reference",
                            "blocker_reference_not_allowed",
                        )
                except _WorkItemError as error:
                    return _invalid_work_item_result(
                        common_directory,
                        "release",
                        args,
                        error,
                        claim,
                    )
            elif args.disposition is not None or args.blocker_reference is not None:
                return _invalid_work_item_result(
                    common_directory,
                    "release",
                    args,
                    _WorkItemError(
                        "Work-item release fields require a work-item claim.",
                        "disposition",
                        "work_item_claim_required",
                    ),
                    claim,
                )
            released = claims.pop(index)
            release_details = (
                {
                    "disposition": args.disposition,
                    "blocker_reference": args.blocker_reference,
                }
                if work_item_id is not None
                else {}
            )
            event = _event(
                "release",
                "RELEASED",
                args,
                claim=released,
                **release_details,
            )
            _write_registry(registry_file, data)
            try:
                journal_path = _append_event(common_directory, event)
            except OSError as error:
                claims.insert(index, released)
                _write_registry(registry_file, data)
                _print_result(
                    "RELEASE_ERROR",
                    journal={"event_id": event["event_id"], "persisted": False},
                    reason="journal_write_failed",
                    message=str(error),
                    claim_id=args.claim_id,
                )
                return ERROR
            _print_result(
                event["outcome"],
                journal={"event_id": event["event_id"], "path": str(journal_path)},
                claim=released,
                **release_details,
            )
            return SUCCESS
        event = _event("release", "CLAIM_NOT_FOUND", args)
        return _journaled_result(
            ERROR,
            common_directory,
            event,
            claim_id=args.claim_id,
        )


def _reset(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry_file(repository, "reset") as (registry_path, registry_file):
        previous_valid = True
        previous_claim_count = 0
        try:
            registry_file.seek(0)
            raw_registry = registry_file.read()
            previous = json.loads(raw_registry) if raw_registry else {"claims": []}
            if not isinstance(previous, dict) or not isinstance(previous.get("claims"), list):
                raise ValueError
            claims = previous["claims"]
            previous_claim_count = len(claims)
        except (json.JSONDecodeError, ValueError):
            previous_valid = False
        _write_registry(registry_file, {"claims": []})
        common_directory = registry_path.parent
        event = _event(
            "reset",
            "RESET",
            args,
            previous_registry_valid=previous_valid,
            removed_claim_count=previous_claim_count if previous_valid else None,
        )
        return _journaled_result(
            SUCCESS,
            common_directory,
            event,
            registry=str(registry_path),
            claims=[],
        )


def _status_command(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    registry_path, data = _read_only_registry(repository)
    evaluated_at = _now()
    _print_result(
        "STATUS",
        registry=str(registry_path),
        claims=[_claim_for_output(claim, evaluated_at) for claim in data["claims"]],
    )
    return SUCCESS


def _event_sort_key(event: dict[str, Any]) -> tuple[str, str]:
    return str(event.get("timestamp", "")), str(event.get("event_id", ""))


def _read_jsonl(raw: bytes, source: str, coverage_gaps: list[dict[str, str]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        coverage_gaps.append(
            {
                "source": source,
                "detail": f"invalid UTF-8 at byte {error.start}",
            }
        )
        return events
    for line_number, raw_line in enumerate(decoded.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as error:
            coverage_gaps.append({"source": source, "detail": f"line {line_number}: {error.msg}"})
            continue
        if not isinstance(event, dict) or not event.get("event_id") or not event.get("timestamp"):
            coverage_gaps.append({"source": source, "detail": f"line {line_number}: invalid event schema"})
            continue
        events.append(event)
    return events


def _load_events(common_directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    _root, hot_directory, archive_directory, _journal = _journal_paths(common_directory)
    coverage_gaps: list[dict[str, str]] = []
    events: list[dict[str, Any]] = []
    for path in sorted(hot_directory.glob("*.jsonl")) if hot_directory.exists() else []:
        try:
            events.extend(_read_jsonl(path.read_bytes(), str(path), coverage_gaps))
        except OSError as error:
            coverage_gaps.append({"source": str(path), "detail": str(error)})
    for path in sorted(archive_directory.glob("**/*.jsonl.gz")) if archive_directory.exists() else []:
        try:
            events.extend(_read_jsonl(gzip.decompress(path.read_bytes()), str(path), coverage_gaps))
        except (OSError, EOFError) as error:
            coverage_gaps.append({"source": str(path), "detail": str(error)})

    unique_events: dict[str, dict[str, Any]] = {}
    for event in sorted(events, key=_event_sort_key):
        event_id = str(event["event_id"])
        if event_id in unique_events:
            coverage_gaps.append({"source": event_id, "detail": "duplicate event id"})
            continue
        unique_events[event_id] = event
    return list(unique_events.values()), coverage_gaps


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _top_counts(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"scope": scope, "count": count}
        for scope, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:10]
    ]


def _aggregate(
    events: list[dict[str, Any]],
    now: datetime,
    live_claims: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(events, key=_event_sort_key)
    normalized_outcomes, normalization_gaps = _normalized_event_outcomes(ordered)
    successful_outcomes = {
        "SHARED_CHECKOUT_ACQUIRED": "primary",
        "ISOLATED_CHECKOUT_ACQUIRED": "isolated",
        "DIRTY_CHECKOUT_RECOVERY_ACQUIRED": "recovery",
    }
    acquisitions = Counter()
    raw_outcome_counts = Counter(str(event.get("outcome")) for event in ordered)
    outcome_counts = Counter(normalized_outcomes)
    action_counts = Counter(str(event.get("action")) for event in ordered)
    acquisition_times: dict[str, datetime] = {}
    released_claims: set[str] = set()
    durations: list[float] = []
    active_waits: dict[tuple[str, str], dict[str, Any]] = {}
    wait_episodes: list[dict[str, Any]] = []
    exact_files: Counter[str] = Counter()
    trees: Counter[str] = Counter()
    resources: Counter[str] = Counter()
    broad_reasons: Counter[str] = Counter()
    broad_scope_count = 0
    broad_file_domains: Counter[str] = Counter()
    integration_resources: Counter[str] = Counter()
    successful_exact_file_adoptions: Counter[str] = Counter()
    journal_warning_count = 0

    for index, event in enumerate(ordered):
        outcome = normalized_outcomes[index]
        action = str(event.get("action"))
        claim_id = str(event.get("claim_id") or "")
        timestamp = _parse_timestamp(str(event["timestamp"]))
        if outcome in successful_outcomes:
            acquisitions[successful_outcomes[outcome]] += 1
            if claim_id:
                acquisition_times[claim_id] = timestamp
        if outcome == "RELEASED" and claim_id:
            released_claims.add(claim_id)
            acquired = acquisition_times.get(claim_id)
            if acquired is not None:
                durations.append(max(0.0, (timestamp - acquired).total_seconds()))

        wait_key = (claim_id, action)
        if outcome == "CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED" and claim_id:
            episode = active_waits.setdefault(
                wait_key,
                {
                    "claim_id": claim_id,
                    "action": action,
                    "started_at": event["timestamp"],
                    "attempt_count": 0,
                },
            )
            episode["attempt_count"] += 1
            episode["last_wait_at"] = event["timestamp"]
        elif wait_key in active_waits and outcome in {*successful_outcomes, "EXTENDED"}:
            episode = active_waits.pop(wait_key)
            episode["resolved_at"] = event["timestamp"]
            episode["duration_seconds"] = max(
                0.0,
                (timestamp - _parse_timestamp(str(episode["started_at"]))).total_seconds(),
            )
            wait_episodes.append(episode)

        if outcome == "CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED":
            for overlap in event.get("overlaps", []):
                if overlap.get("scope_kind") == "resource":
                    resources[str(overlap.get("requested"))] += 1
                elif "tree" in {overlap.get("requested_kind"), overlap.get("claimed_kind")} or "all_files" in {
                    overlap.get("requested_kind"), overlap.get("claimed_kind")
                }:
                    trees[str(overlap.get("requested"))] += 1
                else:
                    exact_files[str(overlap.get("requested"))] += 1

        requested = event.get("requested_scopes") or {}
        if outcome in {*successful_outcomes, "EXTENDED"}:
            adopted_scope = (
                requested
                if outcome in successful_outcomes
                else event.get("added_scope") or {}
            )
            for file_path in adopted_scope.get("files", []):
                successful_exact_file_adoptions[str(file_path)] += 1
            if (
                requested.get("trees")
                or requested.get("project_files")
                or requested.get("backlog")
                or requested.get("all_files")
            ):
                broad_scope_count += 1
                if requested.get("scope_reason"):
                    broad_reasons[str(requested["scope_reason"])] += 1
                requested_domain = _scope_file_domain(requested)
                if requested_domain in {"project_files", "backlog", "all_files"}:
                    broad_file_domains[requested_domain] += 1
            for resource in requested.get("resources", []):
                if str(resource).startswith("merge:integration:"):
                    integration_resources[str(resource)] += 1
        journal_warning_count += len(event.get("journal_warnings", []))

    for episode in active_waits.values():
        episode["resolved_at"] = None
        episode["duration_seconds"] = None
        wait_episodes.append(episode)

    live_by_id = {str(claim.get("claim_id")): claim for claim in live_claims}
    stale_cutoff = now - timedelta(hours=STALE_HEARTBEAT_HOURS)
    stale_claims = sorted(
        claim_id
        for claim_id, claim in live_by_id.items()
        if claim.get("heartbeat") and _parse_timestamp(str(claim["heartbeat"])) < stale_cutoff
    )
    missing_releases = sorted(
        claim_id
        for claim_id in acquisition_times
        if claim_id not in released_claims and claim_id not in live_by_id
    )
    return {
        "action_counts": dict(sorted(action_counts.items())),
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "raw_outcome_counts": dict(sorted(raw_outcome_counts.items())),
        "outcome_normalization_gaps": normalization_gaps,
        "successful_acquisitions": {
            mode: acquisitions.get(mode, 0) for mode in ("primary", "isolated", "recovery")
        },
        "wait_episodes": sorted(wait_episodes, key=lambda item: (item["started_at"], item["claim_id"])),
        "wait_attempt_count": outcome_counts.get("CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED", 0),
        "claim_duration_seconds": {
            "count": len(durations),
            "median": median(durations) if durations else None,
            "p95": _percentile(durations, 0.95),
            "maximum": max(durations) if durations else None,
        },
        "top_contention": {
            "exact_files": _top_counts(exact_files),
            "trees": _top_counts(trees),
            "resources": _top_counts(resources),
        },
        "broad_scopes": {
            "event_count": broad_scope_count,
            "file_domains": {
                domain: broad_file_domains.get(domain, 0)
                for domain in ("all_files", "backlog", "project_files")
            },
            "reasons": _top_counts(broad_reasons),
        },
        "successful_scope_adoptions": {
            "exact_files": _top_counts(successful_exact_file_adoptions),
        },
        "open_claim_ids": sorted(live_by_id),
        "claims_with_missing_release": missing_releases,
        "stale_heartbeat_claim_ids": stale_claims,
        "integration_resources": _top_counts(integration_resources),
        "journal_warning_count": journal_warning_count,
    }


def _daily_summary(day: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = _aggregate(events, _now(), [])
    event_ids = sorted(str(event["event_id"]) for event in events)
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "date": day,
        "raw_event_count": len(events),
        "event_ids_sha256": hashlib.sha256("\n".join(event_ids).encode("utf-8")).hexdigest(),
        "action_counts": metrics["action_counts"],
        "outcome_counts": metrics["outcome_counts"],
        "raw_outcome_counts": metrics["raw_outcome_counts"],
        "claim_duration_seconds": metrics["claim_duration_seconds"],
        "wait_episodes": metrics["wait_episodes"],
        "top_contention": metrics["top_contention"],
        "recovery_event_count": metrics["outcome_counts"].get(
            "DIRTY_CHECKOUT_RECOVERY_ACQUIRED",
            0,
        ),
        "incomplete_lifecycle_claim_ids": metrics["claims_with_missing_release"],
    }


def _gzip_bytes(raw: bytes) -> bytes:
    from io import BytesIO

    destination = BytesIO()
    with gzip.GzipFile(fileobj=destination, mode="wb", mtime=0) as compressed:
        compressed.write(raw)
    return destination.getvalue()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_validated_archive(path: Path, compressed: bytes, expected_raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(compressed)
            stream.flush()
            os.fsync(stream.fileno())
        if os.environ.get("AGENT_CLAIM_TEST_FAIL_ARCHIVE_BEFORE_VALIDATE") == "1":
            raise OSError("simulated interruption before archive validation")
        if gzip.decompress(temporary.read_bytes()) != expected_raw:
            raise ValueError(f"Archive validation failed for {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _maintain_journal(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    if args.hot_days < 1:
        _print_result("INVALID_HOT_DAYS", hot_days=args.hot_days)
        return ERROR
    cutoff = _now().date() - timedelta(days=args.hot_days - 1)
    archived: list[dict[str, Any]] = []
    try:
        with _locked_registry(repository, "maintain-journal") as (registry_path, _data, _registry_file):
            state_root = registry_path.parent
            _root, hot_directory, archive_directory, journal_directory = _journal_paths(state_root)
            with _maintenance_lock(state_root):
                candidates = sorted(hot_directory.glob("*.jsonl")) if hot_directory.exists() else []
                for hot_path in candidates:
                    match = UTC_DAY_PATTERN.match(hot_path.name)
                    if not match:
                        continue
                    day_text = match.group(1)
                    day = date.fromisoformat(day_text)
                    if day >= cutoff:
                        continue
                    raw = hot_path.read_bytes()
                    coverage_gaps: list[dict[str, str]] = []
                    events = _read_jsonl(raw, str(hot_path), coverage_gaps)
                    if coverage_gaps:
                        raise ValueError(f"Cannot archive invalid journal {hot_path}: {coverage_gaps}")

                    year, month, _day = day_text.split("-")
                    archive_path = archive_directory / year / month / f"{day_text}.jsonl.gz"
                    summary_path = journal_directory / year / month / f"{day_text}.json"
                    compressed = _gzip_bytes(raw)

                    if archive_path.exists():
                        if gzip.decompress(archive_path.read_bytes()) != raw:
                            raise ValueError(f"Existing immutable archive does not match {hot_path}")
                    else:
                        _write_validated_archive(archive_path, compressed, raw)
                    if gzip.decompress(archive_path.read_bytes()) != raw:
                        raise ValueError(f"Archive validation failed for {archive_path}")

                    summary = _daily_summary(day_text, events)
                    rendered_summary = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
                    if summary_path.exists():
                        if summary_path.read_bytes() != rendered_summary:
                            raise ValueError(f"Existing immutable summary does not match {hot_path}")
                    else:
                        _atomic_write(summary_path, rendered_summary)
                    hot_path.unlink()
                    archived.append(
                        {
                            "date": day_text,
                            "event_count": len(events),
                            "archive": str(archive_path),
                            "summary": str(summary_path),
                        }
                    )
    except (OSError, ValueError) as error:
        _print_result("JOURNAL_MAINTENANCE_FAILED", message=str(error), archived=archived)
        return ERROR
    _print_result("JOURNAL_MAINTAINED", hot_days=args.hot_days, archived=archived)
    return SUCCESS


def _since_delta(value: str) -> timedelta:
    match = SINCE_PATTERN.match(value)
    if not match:
        raise ValueError("--since must use a positive duration such as 12h or 2d")
    amount = int(match.group(1))
    if amount < 1:
        raise ValueError("--since must be positive")
    return timedelta(hours=amount) if match.group(2) == "h" else timedelta(days=amount)


def _render_text_report(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    acquisitions = metrics["successful_acquisitions"]
    exact_file_adoptions = metrics["successful_scope_adoptions"]["exact_files"]
    rendered_exact_file_adoptions = ", ".join(
        f"{item['scope']}={item['count']}"
        for item in exact_file_adoptions
    ) or "none"
    durations = metrics["claim_duration_seconds"]
    return "\n".join(
        (
            f"Claim report {report['window']['start']} to {report['window']['end']}",
            f"Events: {report['event_count']}",
            "Acquisitions: "
            f"primary={acquisitions['primary']} isolated={acquisitions['isolated']} recovery={acquisitions['recovery']}",
            f"Successful exact-file adoptions: {rendered_exact_file_adoptions}",
            f"Wait attempts: {metrics['wait_attempt_count']} in {len(metrics['wait_episodes'])} episodes",
            "Claim duration seconds: "
            f"median={durations['median']} p95={durations['p95']} maximum={durations['maximum']}",
            f"Open claims: {', '.join(metrics['open_claim_ids']) or 'none'}",
            f"Coverage gaps: {len(report['coverage_gaps'])}",
        )
    )


def _work_item_report(
    events: Sequence[dict[str, Any]],
    live_claims: Sequence[dict[str, Any]],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    successful_acquisitions = {
        "SHARED_CHECKOUT_ACQUIRED",
        "ISOLATED_CHECKOUT_ACQUIRED",
        "DIRTY_CHECKOUT_RECOVERY_ACQUIRED",
    }
    live_identities = {
        (str(claim.get("claim_id") or ""), str(claim.get("incarnation_id") or ""))
        for claim in live_claims
        if claim.get("work_item_id")
    }
    segments_by_work_item: dict[str, list[dict[str, Any]]] = {}
    open_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    open_by_work_item: dict[str, list[dict[str, Any]]] = {}
    missing_release_event_ids: list[str] = []
    release_without_acquisition_event_ids: list[str] = []
    contradictory_event_ids: list[str] = []
    historical_non_work_item_event_ids: list[str] = []

    def in_window(event: dict[str, Any]) -> bool:
        timestamp = _parse_timestamp(str(event.get("timestamp")))
        return start <= timestamp <= end

    for event in sorted(events, key=_event_sort_key):
        event_id = str(event.get("event_id") or "")
        work_item_id = event.get("work_item_id")
        if not isinstance(work_item_id, str) or not work_item_id:
            if in_window(event):
                historical_non_work_item_event_ids.append(event_id)
            continue
        action = str(event.get("action") or "")
        outcome = _canonical_outcome(str(event.get("outcome") or ""))
        identity = (
            str(event.get("claim_id") or ""),
            str(event.get("incarnation_id") or ""),
        )
        if action == "acquire" and outcome in successful_acquisitions:
            activity = event.get("activity")
            if activity not in {"work", "update"} or open_by_work_item.get(work_item_id):
                if in_window(event):
                    contradictory_event_ids.append(event_id)
                continue
            segment = {
                "work_item_id": work_item_id,
                "claim_id": identity[0],
                "incarnation_id": identity[1] or None,
                "owner": event.get("agent"),
                "root_task_id": event.get("root_task_id"),
                "activity": activity,
                "acquired_at": event.get("timestamp"),
                "released_at": None,
                "disposition": None,
                "blocker_reference": None,
                "duration_seconds": None,
                "open": True,
                "live": identity in live_identities,
                "acquisition_event_id": event_id,
                "release_event_id": None,
            }
            segments_by_work_item.setdefault(work_item_id, []).append(segment)
            open_by_identity[identity] = segment
            open_by_work_item.setdefault(work_item_id, []).append(segment)
        elif action == "release" and outcome == "RELEASED":
            segment = open_by_identity.get(identity)
            if segment is None:
                if in_window(event):
                    release_without_acquisition_event_ids.append(event_id)
                continue
            disposition = event.get("disposition")
            blocker_reference = event.get("blocker_reference")
            contradictory = (
                work_item_id != segment["work_item_id"]
                or event.get("activity") != segment["activity"]
                or event.get("agent") != segment["owner"]
                or event.get("root_task_id") != segment["root_task_id"]
                or disposition not in {"done", "blocked", "handoff"}
                or (
                    disposition == "blocked"
                    and blocker_reference is not None
                    and not _valid_blocker_reference(blocker_reference)
                )
                or disposition != "blocked" and blocker_reference is not None
            )
            if contradictory:
                if in_window(event):
                    contradictory_event_ids.append(event_id)
                continue
            released_at = str(event.get("timestamp"))
            segment["released_at"] = released_at
            segment["disposition"] = disposition
            segment["blocker_reference"] = blocker_reference
            segment["duration_seconds"] = max(
                0.0,
                (
                    _parse_timestamp(released_at)
                    - _parse_timestamp(str(segment["acquired_at"]))
                ).total_seconds(),
            )
            segment["open"] = False
            segment["live"] = False
            segment["release_event_id"] = event_id
            open_by_identity.pop(identity, None)
            open_by_work_item[work_item_id].remove(segment)
            if not open_by_work_item[work_item_id]:
                open_by_work_item.pop(work_item_id)

    for segments in segments_by_work_item.values():
        for segment in segments:
            identity = (
                str(segment["claim_id"] or ""),
                str(segment["incarnation_id"] or ""),
            )
            segment["live"] = identity in live_identities
            acquired_at = _parse_timestamp(str(segment["acquired_at"]))
            if segment["open"] and not segment["live"] and acquired_at <= end:
                missing_release_event_ids.append(str(segment["acquisition_event_id"]))

    filtered_items: list[dict[str, Any]] = []
    for work_item_id, segments in sorted(segments_by_work_item.items()):
        visible_segments = []
        for segment in segments:
            acquired_at = _parse_timestamp(str(segment["acquired_at"]))
            released_at = (
                _parse_timestamp(str(segment["released_at"]))
                if segment["released_at"] is not None
                else None
            )
            if acquired_at <= end and (released_at is None or released_at >= start):
                rendered = dict(segment)
                rendered.pop("work_item_id")
                visible_segments.append(rendered)
        if visible_segments:
            filtered_items.append(
                {
                    "work_item_id": work_item_id,
                    "segments": sorted(
                        visible_segments,
                        key=lambda segment: (
                            str(segment["acquired_at"]),
                            str(segment["claim_id"]),
                        ),
                    ),
                }
            )

    return {
        "schema_version": WORK_ITEM_REPORT_SCHEMA_VERSION,
        "items": filtered_items,
        "diagnostics": {
            "missing_release_event_ids": sorted(missing_release_event_ids),
            "release_without_acquisition_event_ids": sorted(
                release_without_acquisition_event_ids
            ),
            "contradictory_event_ids": sorted(contradictory_event_ids),
            "historical_non_work_item_event_ids": sorted(
                historical_non_work_item_event_ids
            ),
        },
    }


def _report(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    try:
        delta = _since_delta(args.since)
    except ValueError as error:
        _print_result("INVALID_SINCE", message=str(error))
        return ERROR
    end = _now()
    start = end - delta
    registry_path, data = _read_only_registry(repository)
    state_marker = _state_marker(repository)
    if state_marker is None:
        legacy_events = _legacy_events_path(repository)
        event_state_root = legacy_events.parent if legacy_events.is_dir() else registry_path.parent
    else:
        event_state_root = registry_path.parent
    events, coverage_gaps = _load_events(event_state_root)
    filtered = [
        event
        for event in events
        if start <= _parse_timestamp(str(event["timestamp"])) <= end
    ]
    live_claims = [dict(claim) for claim in data["claims"]]
    acquired_claim_ids = {
        str(event.get("claim_id"))
        for event in events
        if _canonical_outcome(str(event.get("outcome")))
        in {
            "SHARED_CHECKOUT_ACQUIRED",
            "ISOLATED_CHECKOUT_ACQUIRED",
            "DIRTY_CHECKOUT_RECOVERY_ACQUIRED",
        }
    }
    for claim in live_claims:
        claim_id = str(claim.get("claim_id"))
        if claim_id not in acquired_claim_ids:
            coverage_gaps.append(
                {"source": claim_id, "detail": "live claim has no acquisition event"}
            )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "window": {"since": args.since, "start": _format_timestamp(start), "end": _format_timestamp(end)},
        "event_count": len(filtered),
        "metrics": _aggregate(filtered, end, live_claims),
        "work_items": _work_item_report(events, live_claims, start, end),
        "coverage_gaps": coverage_gaps,
    }
    if args.format == "text":
        print(_render_text_report(report))
    else:
        _emit_result(report)
    return SUCCESS


def _add_scope_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--file", action="append", default=[], help="Exact intended file; future nonexistent files are allowed.")
    parser.add_argument("--tree", action="append", default=[], help="Intended directory subtree.")
    parser.add_argument(
        "--project-files",
        action="store_true",
        help="Claim every project file except the primary-only backlog and ignored operational state.",
    )


def _add_resource_timing_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--resource-class")
    parser.add_argument("--resource-id")
    parser.add_argument("--expected-duration-seconds", type=int)
    parser.add_argument("--requested-hard-stop-duration-seconds", type=int)
    parser.add_argument(
        "--backlog",
        action="store_true",
        help="Claim the complete primary-worktree-only backlog subtree.",
    )
    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Claim the explicit union of project files and backlog.",
    )
    parser.add_argument("--resource", action="append", default=[], help="Exclusive repository-global runtime resource.")
    parser.add_argument(
        "--scope-reason",
        help="Bounded coordination-only reason required for tree or broad file-domain scope.",
    )
    parser.add_argument(
        "--compat-file-directories",
        action="store_true",
        help="Temporarily convert existing directories passed through --file into warned tree scopes.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate repository claims, worktrees, and claim diagnostics.")
    parser.add_argument("--repo", default=".", help="Path inside the repository.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire = subparsers.add_parser("acquire", help="Atomically acquire scoped ownership.")
    acquire.add_argument("--claim-id", required=True)
    acquire.add_argument("--agent", required=True)
    acquire.add_argument("--task", required=True)
    acquire.add_argument("--root-task-id", required=True)
    acquire.add_argument("--parent-claim-id")
    acquire.add_argument("--work-item-id")
    acquire.add_argument("--activity")
    _add_scope_arguments(acquire)
    acquire.add_argument("--branch")
    acquire.add_argument(
        "--worktree-path",
        help="Compatibility input that must equal the canonical primary-root .worktrees target.",
    )
    acquire.add_argument("--base", default="HEAD")
    _add_resource_timing_arguments(acquire)
    acquire.set_defaults(handler=_acquire)

    extend = subparsers.add_parser("extend", help="Atomically add files, trees, or resources to an active claim.")
    extend.add_argument("--claim-id", required=True)
    _add_scope_arguments(extend)
    _add_resource_timing_arguments(extend)
    extend.set_defaults(handler=_extend)

    heartbeat = subparsers.add_parser("heartbeat", help="Refresh an active claim heartbeat.")
    heartbeat.add_argument("--claim-id", required=True)
    heartbeat.set_defaults(handler=_heartbeat)

    extend_deadline = subparsers.add_parser(
        "extend-deadline",
        help="Extend one configured resource hard stop with bounded evidence.",
    )
    extend_deadline.add_argument("--claim-id", required=True)
    extend_deadline.add_argument(
        "--requested-hard-stop-duration-seconds",
        required=True,
        type=int,
    )
    extend_deadline.add_argument("--extension-evidence", required=True)
    extend_deadline.set_defaults(handler=_extend_deadline)

    release = subparsers.add_parser("release", help="Remove one exact live claim and journal its release.")
    release.add_argument("--claim-id", required=True)
    release.add_argument("--disposition")
    release.add_argument("--blocker-reference")
    release.set_defaults(handler=_release)

    reset = subparsers.add_parser("reset", help="Replace the live claim registry with an empty claim list.")
    reset.set_defaults(handler=_reset)

    status = subparsers.add_parser("status", help="Show the repository-global live claim registry.")
    status.set_defaults(handler=_status_command)

    maintain = subparsers.add_parser("maintain-journal", help="Archive complete UTC journal days outside the hot window.")
    maintain.add_argument("--hot-days", type=int, default=DEFAULT_HOT_DAYS)
    maintain.set_defaults(handler=_maintain_journal)

    report = subparsers.add_parser("report", help="Report claim contention from the journal and live registry.")
    report.add_argument("--since", default="2d")
    report.add_argument("--format", choices=("json", "text"), default="json")
    report.set_defaults(handler=_report)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one public claim command.

    Args:
        argv: Optional command arguments without the executable name. Process arguments
            are used when this value is absent.

    Returns:
        The stable command exit code. Commands may mutate the live registry, worktrees,
        or journal according to their documented boundary; report remains read-only.
    """
    args = _parser().parse_args(argv)
    return _execute(args)


def _execute(args: argparse.Namespace) -> int:
    try:
        return args.handler(args)
    except _ClaimStateError as error:
        _print_result(
            "CLAIM_STATE_MIGRATION_BLOCKED",
            reason=error.reason,
            message=str(error),
            registry_unchanged=True,
            **error.details,
        )
        return COORDINATION_REQUIRED_EXIT_CODE


def dispatch(argv: Sequence[str]) -> tuple[dict[str, Any], int]:
    """Dispatch one claim command and return its structured result without stdout capture.

    Args:
        argv: Complete command arguments without the executable name. Callers must request
            JSON reporting because text reports are a CLI presentation contract.

    Returns:
        The single structured result document and stable command exit code.

    Raises:
        ValueError: If the selected handler does not emit exactly one structured result.

    Command side effects and repository-global locking are identical to ``main``. Result
    collection is context-local, so unrelated repository calls may run concurrently.
    """
    args = _parser().parse_args(argv)
    captured: list[dict[str, Any]] = []
    token = _RESULT_SINK.set(captured)
    try:
        exit_code = _execute(args)
    finally:
        _RESULT_SINK.reset(token)
    if len(captured) != 1:
        raise ValueError(
            f"Claim command emitted {len(captured)} structured results; expected exactly one."
        )
    return captured[0], exit_code


if __name__ == "__main__":
    raise SystemExit(main())
