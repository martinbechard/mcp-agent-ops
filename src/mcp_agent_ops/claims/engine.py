#!/usr/bin/env python3
# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Coordinates claims, journaling, reporting, isolation, recovery, and release.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import subprocess
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterator, Sequence
from uuid import uuid4


SUCCESS = 0
ERROR = 1
WAIT = 3
ISOLATE_REQUIRED = 4
RECOVERY_REQUIRED = 5
REGISTRY_FILE_NAME = "agent-claims.json"
LOCK_FILE_NAME = "agent-claims.lock"
EVENT_DIRECTORY_NAME = "agent-claim-events"
EVENT_SCHEMA_VERSION = 1
SUMMARY_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
DEFAULT_HOT_DAYS = 2
MAX_SCOPE_REASON_LENGTH = 200
MAX_IDENTIFIER_LENGTH = 200
STALE_HEARTBEAT_HOURS = 24
UTC_DAY_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.jsonl$")
SINCE_PATTERN = re.compile(r"^(\d+)([dh])$")
_RESULT_SINK: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "claim_result_sink",
    default=None,
)


class _ScopeError(ValueError):
    def __init__(self, message: str, offending_scope: str, replacement: str) -> None:
        super().__init__(message)
        self.offending_scope = offending_scope
        self.replacement = replacement


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


def _registry_paths(repository: Path) -> tuple[Path, Path]:
    common_directory = _git_common_directory(repository)
    return common_directory / REGISTRY_FILE_NAME, common_directory / LOCK_FILE_NAME


def _journal_paths(common_directory: Path) -> tuple[Path, Path, Path, Path]:
    root = common_directory / EVENT_DIRECTORY_NAME
    return root, root / "hot", root / "archive", root / "journal"


@contextmanager
def _locked_registry(repository: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    registry_path, lock_path = _registry_paths(repository)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            if registry_path.exists():
                data = json.loads(registry_path.read_text(encoding="utf-8"))
            else:
                data = {"claims": []}
            if not isinstance(data.get("claims"), list):
                raise ValueError(f"Invalid claim registry: {registry_path}")
            yield registry_path, data
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@contextmanager
def _maintenance_lock(common_directory: Path) -> Iterator[None]:
    root, _hot, _archive, _journal = _journal_paths(common_directory)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "maintenance.lock").open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_registry(path: Path, data: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_path, path)


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


def _status(worktree: Path) -> str:
    return _git(worktree, "status", "--porcelain").stdout


def _head(worktree: Path) -> str:
    return _git(worktree, "rev-parse", "HEAD").stdout.strip()


def _branch(worktree: Path) -> str:
    return _git(worktree, "branch", "--show-current").stdout.strip()


def _bounded_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()[:MAX_IDENTIFIER_LENGTH]


def _deduplicate(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _normalize_repository_path(repository: Path, value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise _ScopeError("Scope paths cannot be empty.", value, "provide a repository-relative path")
    if any(character in stripped for character in "*?["):
        raise _ScopeError(
            "Wildcard scopes are not supported.",
            stripped,
            "use --tree <path> or --all-files",
        )
    candidate = Path(stripped)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(repository)
        except ValueError as error:
            raise _ScopeError(
                "Scope paths must remain inside the repository.",
                stripped,
                "provide a repository-relative path",
            ) from error
    normalized = Path(os.path.normpath(str(candidate))).as_posix()
    if normalized == ".." or normalized.startswith("../"):
        raise _ScopeError(
            "Scope paths must remain inside the repository.",
            stripped,
            "provide a repository-relative path",
        )
    return normalized.rstrip("/") or "."


def _empty_scope() -> dict[str, Any]:
    return {
        "files": [],
        "trees": [],
        "all_files": False,
        "resources": [],
        "scope_reason": None,
    }


def _scope_from_args(args: argparse.Namespace, repository: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    scope = _empty_scope()
    warnings: list[dict[str, str]] = []
    compatibility = bool(getattr(args, "compat_file_directories", False))

    for raw_file in getattr(args, "file", []):
        normalized = _normalize_repository_path(repository, raw_file)
        if normalized == ".":
            raise _ScopeError(
                "Repository-wide ownership cannot be requested through --file.",
                raw_file,
                "use --all-files with --scope-reason",
            )
        if (repository / normalized).is_dir():
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

    for raw_tree in getattr(args, "tree", []):
        normalized = _normalize_repository_path(repository, raw_tree)
        if normalized == ".":
            raise _ScopeError(
                "Repository root cannot be requested as a tree.",
                raw_tree,
                "use --all-files with --scope-reason",
            )
        if (repository / normalized).is_file():
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
    scope["all_files"] = bool(getattr(args, "all_files", False))

    reason = getattr(args, "scope_reason", None)
    if reason is not None:
        reason = reason.strip()
        if not reason or "\n" in reason or "\r" in reason or len(reason) > MAX_SCOPE_REASON_LENGTH:
            raise _ScopeError(
                f"Scope reasons must contain 1 to {MAX_SCOPE_REASON_LENGTH} single-line characters.",
                reason,
                "provide a short coordination-only --scope-reason",
            )
    if (scope["trees"] or scope["all_files"]) and not reason:
        raise _ScopeError(
            "Broad tree and repository-wide scopes require a reason.",
            ", ".join(scope["trees"]) or ".",
            "add --scope-reason with bounded coordination-only text",
        )
    scope["scope_reason"] = reason
    return scope, warnings


def _claim_scope(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "files": [str(value) for value in claim.get("files", [])],
        "trees": [str(value) for value in claim.get("trees", [])],
        "all_files": bool(claim.get("all_files", False)),
        "resources": [str(value) for value in claim.get("resources", [])],
        "scope_reasons": dict(claim.get("scope_reasons", {})),
    }


def _path_is_within(path: str, tree: str) -> bool:
    return path == tree or path.startswith(tree + "/")


def _path_scope_overlap(
    requested_kind: str,
    requested_path: str,
    claimed_kind: str,
    claimed_path: str,
) -> bool:
    if "all_files" in {requested_kind, claimed_kind}:
        return True
    if requested_kind == "file" and claimed_kind == "file":
        return requested_path == claimed_path
    if requested_kind == "tree" and claimed_kind == "tree":
        return _path_is_within(requested_path, claimed_path) or _path_is_within(claimed_path, requested_path)
    if requested_kind == "tree":
        return _path_is_within(claimed_path, requested_path)
    return _path_is_within(requested_path, claimed_path)


def _path_scopes(scope: dict[str, Any]) -> list[tuple[str, str]]:
    values = [("file", value) for value in scope.get("files", [])]
    values.extend(("tree", value) for value in scope.get("trees", []))
    if scope.get("all_files"):
        values.append(("all_files", "."))
    return values


def _overlap_details(requested: dict[str, Any], claimed: dict[str, Any]) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for requested_kind, requested_path in _path_scopes(requested):
        for claimed_kind, claimed_path in _path_scopes(claimed):
            if _path_scope_overlap(requested_kind, requested_path, claimed_kind, claimed_path):
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
    excluded_claim_id: str | None = None,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    for claim in claims:
        if claim.get("claim_id") == excluded_claim_id:
            continue
        details = _overlap_details(requested, _claim_scope(claim))
        if details:
            conflicts.append({"claim_id": claim["claim_id"], "overlaps": details})
    return conflicts


def _scope_reasons(scope: dict[str, Any]) -> dict[str, str]:
    reason = scope.get("scope_reason")
    if not reason:
        return {}
    reasons = {f"tree:{path}": reason for path in scope.get("trees", [])}
    if scope.get("all_files"):
        reasons["all_files:."] = reason
    return reasons


def _owned_and_added_scope(claim: dict[str, Any], requested: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    current = _claim_scope(claim)
    added = _empty_scope()
    owned = _empty_scope()

    for file_path in requested["files"]:
        target = owned if (
            current["all_files"]
            or file_path in current["files"]
            or any(_path_is_within(file_path, tree) for tree in current["trees"])
        ) else added
        target["files"].append(file_path)
    for tree_path in requested["trees"]:
        target = owned if (
            current["all_files"]
            or any(_path_is_within(tree_path, tree) for tree in current["trees"])
        ) else added
        target["trees"].append(tree_path)
    if requested["all_files"]:
        (owned if current["all_files"] else added)["all_files"] = True
    current_resources = set(current["resources"])
    for resource in requested["resources"]:
        (owned if resource in current_resources else added)["resources"].append(resource)

    added["scope_reason"] = requested.get("scope_reason")
    owned["scope_reason"] = requested.get("scope_reason")
    return owned, added


def _scope_has_values(scope: dict[str, Any]) -> bool:
    return bool(scope["files"] or scope["trees"] or scope["all_files"] or scope["resources"])


def _apply_scope(claim: dict[str, Any], added: dict[str, Any]) -> None:
    claim["files"] = _deduplicate([*claim.get("files", []), *added["files"]])
    claim["trees"] = _deduplicate([*claim.get("trees", []), *added["trees"]])
    claim["all_files"] = bool(claim.get("all_files", False) or added["all_files"])
    claim["resources"] = _deduplicate([*claim.get("resources", []), *added["resources"]])
    reasons = dict(claim.get("scope_reasons", {}))
    reasons.update(_scope_reasons(added))
    claim["scope_reasons"] = reasons


def _worktree_identifier(claim: dict[str, Any]) -> str | None:
    mode = claim.get("mode")
    if mode in {"primary", "recovery"}:
        return "primary"
    branch = claim.get("branch")
    return str(branch) if branch else None


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
        "worktree_id": _worktree_identifier(claim) if claim else None,
        "baseline_commit": claim.get("baseline_commit") if claim else None,
        "resulting_commit": extra.pop("resulting_commit", None),
        "command_warnings": extra.pop("command_warnings", []),
        "journal_warnings": [],
    }
    event.update(extra)
    return event


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


def _print_result(outcome: str, **details: Any) -> None:
    _emit_result({"outcome": outcome, **details})


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
    _print_result(event["outcome"], journal=journal, **details)
    return code


def _invalid_scope_result(
    common_directory: Path,
    action: str,
    args: argparse.Namespace,
    error: _ScopeError,
) -> int:
    event = _event(
        action,
        "INVALID_SCOPE",
        args,
        rejection={
            "message": str(error),
            "offending_scope": error.offending_scope,
            "replacement": error.replacement,
        },
    )
    return _journaled_result(
        ERROR,
        common_directory,
        event,
        message=str(error),
        offending_scope=error.offending_scope,
        replacement=error.replacement,
    )


def _acquire(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository) as (registry_path, data):
        common_directory = registry_path.parent
        try:
            requested_scope, scope_warnings = _scope_from_args(args, repository)
        except _ScopeError as error:
            return _invalid_scope_result(common_directory, "acquire", args, error)

        claims: list[dict[str, Any]] = data["claims"]
        if any(claim.get("claim_id") == args.claim_id for claim in claims):
            event = _event("acquire", "CLAIM_ID_EXISTS", args, requested_scope=requested_scope)
            return _journaled_result(ERROR, common_directory, event, claim_id=args.claim_id)

        conflicts = _conflicts(claims, requested_scope)
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
                WAIT,
                common_directory,
                event,
                scope_warnings,
                conflicting_claim_ids=[item["claim_id"] for item in conflicts],
                overlaps=event["overlaps"],
            )

        if claims:
            if not args.branch or not args.worktree_path:
                event = _event(
                    "acquire",
                    "ISOLATE_REQUIRED",
                    args,
                    requested_scope=requested_scope,
                    active_claim_count=len(claims),
                    command_warnings=scope_warnings,
                )
                return _journaled_result(
                    ISOLATE_REQUIRED,
                    common_directory,
                    event,
                    scope_warnings,
                    active_claim_count=len(claims),
                )
            target_worktree = Path(args.worktree_path).resolve()
            completed = _git(
                repository,
                "worktree",
                "add",
                "-b",
                args.branch,
                str(target_worktree),
                args.base,
                check=False,
            )
            if completed.returncode != SUCCESS:
                event = _event(
                    "acquire",
                    "WORKTREE_CREATE_FAILED",
                    args,
                    requested_scope=requested_scope,
                    reason="git_worktree_create_failed",
                )
                return _journaled_result(ERROR, common_directory, event, message="Git worktree creation failed.")
            mode = "isolated"
            outcome = "ISOLATE"
        else:
            target_worktree = repository
            initial_status = _status(target_worktree)
            if initial_status and not args.allow_recovery:
                event = _event(
                    "acquire",
                    "RECOVERY_REQUIRED",
                    args,
                    requested_scope=requested_scope,
                    dirty_paths=[line[3:] for line in initial_status.splitlines()],
                    command_warnings=scope_warnings,
                )
                return _journaled_result(
                    RECOVERY_REQUIRED,
                    common_directory,
                    event,
                    scope_warnings,
                    dirty_status=initial_status.splitlines(),
                )
            mode = "recovery" if initial_status else "primary"
            outcome = "RECOVER" if initial_status else "PRIMARY"

        now = _timestamp()
        claim = {
            "agent": args.agent,
            "all_files": requested_scope["all_files"],
            "baseline_commit": _head(target_worktree),
            "baseline_status": _status(target_worktree).splitlines(),
            "branch": _branch(target_worktree),
            "claim_id": args.claim_id,
            "claimed_at": now,
            "files": requested_scope["files"],
            "heartbeat": now,
            "mode": mode,
            "parent_claim_id": args.parent_claim_id,
            "resources": requested_scope["resources"],
            "root_task_id": args.root_task_id,
            "scope_reasons": _scope_reasons(requested_scope),
            "task": args.task,
            "trees": requested_scope["trees"],
            "worktree": str(target_worktree),
        }
        claims.append(claim)
        _write_registry(registry_path, data)
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
            target={"mode": mode, "branch": claim["branch"], "worktree": str(target_worktree)},
        )


def _extend(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository) as (registry_path, data):
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

        already_owned, added = _owned_and_added_scope(claim, requested_scope)
        conflicts = _conflicts(claims, added, excluded_claim_id=args.claim_id) if _scope_has_values(added) else []
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
                WAIT,
                common_directory,
                event,
                scope_warnings,
                conflicting_claim_ids=[item["claim_id"] for item in conflicts],
                overlaps=event["overlaps"],
                added_scope=added,
                already_owned_scope=already_owned,
            )

        if _scope_has_values(added):
            _apply_scope(claim, added)
            _write_registry(registry_path, data)
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
    with _locked_registry(repository) as (registry_path, data):
        common_directory = registry_path.parent
        for claim in data["claims"]:
            if claim.get("claim_id") == args.claim_id:
                claim["heartbeat"] = _timestamp()
                _write_registry(registry_path, data)
                event = _event("heartbeat", "HEARTBEAT", args, claim=claim)
                return _journaled_result(SUCCESS, common_directory, event, claim=claim)
        event = _event("heartbeat", "CLAIM_NOT_FOUND", args)
        return _journaled_result(ERROR, common_directory, event, claim_id=args.claim_id)


def _release(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository) as (registry_path, data):
        common_directory = registry_path.parent
        claims: list[dict[str, Any]] = data["claims"]
        for index, claim in enumerate(claims):
            if claim.get("claim_id") != args.claim_id:
                continue
            worktree = Path(claim["worktree"])
            if _status(worktree):
                event = _event("release", "RELEASE_REJECTED", args, claim=claim, reason="worktree_not_clean")
                return _journaled_result(ERROR, common_directory, event, reason="worktree_not_clean")
            resulting_commit = _head(worktree)
            if resulting_commit == claim.get("baseline_commit") and not args.no_change:
                event = _event(
                    "release",
                    "RELEASE_REJECTED",
                    args,
                    claim=claim,
                    resulting_commit=resulting_commit,
                    reason="missing_commit_or_no_change",
                )
                return _journaled_result(ERROR, common_directory, event, reason="missing_commit_or_no_change")
            released = claims.pop(index)
            _write_registry(registry_path, data)
            event = _event(
                "release",
                "RELEASED",
                args,
                claim=released,
                resulting_commit=resulting_commit,
                no_change=args.no_change,
            )
            return _journaled_result(SUCCESS, common_directory, event, claim=released)
        event = _event("release", "CLAIM_NOT_FOUND", args)
        return _journaled_result(ERROR, common_directory, event, claim_id=args.claim_id)


def _status_command(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    with _locked_registry(repository) as (registry_path, data):
        _print_result("STATUS", registry=str(registry_path), claims=data["claims"])
    return SUCCESS


def _event_sort_key(event: dict[str, Any]) -> tuple[str, str]:
    return str(event.get("timestamp", "")), str(event.get("event_id", ""))


def _read_jsonl(raw: bytes, source: str, coverage_gaps: list[dict[str, str]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(raw.decode("utf-8").splitlines(), start=1):
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


def _aggregate(events: list[dict[str, Any]], now: datetime, live_claims: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(events, key=_event_sort_key)
    successful_outcomes = {"PRIMARY": "primary", "ISOLATE": "isolated", "RECOVER": "recovery"}
    acquisitions = Counter()
    outcome_counts = Counter(str(event.get("outcome")) for event in ordered)
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
    integration_resources: Counter[str] = Counter()
    journal_warning_count = 0

    for event in ordered:
        outcome = str(event.get("outcome"))
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
        if outcome == "WAIT" and claim_id:
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
        elif wait_key in active_waits and outcome in {"PRIMARY", "ISOLATE", "RECOVER", "EXTENDED"}:
            episode = active_waits.pop(wait_key)
            episode["resolved_at"] = event["timestamp"]
            episode["duration_seconds"] = max(
                0.0,
                (timestamp - _parse_timestamp(str(episode["started_at"]))).total_seconds(),
            )
            wait_episodes.append(episode)

        if outcome == "WAIT":
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
        if outcome in {"PRIMARY", "ISOLATE", "RECOVER", "EXTENDED"}:
            if requested.get("trees") or requested.get("all_files"):
                broad_scope_count += 1
                if requested.get("scope_reason"):
                    broad_reasons[str(requested["scope_reason"])] += 1
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
        "successful_acquisitions": {
            mode: acquisitions.get(mode, 0) for mode in ("primary", "isolated", "recovery")
        },
        "wait_episodes": sorted(wait_episodes, key=lambda item: (item["started_at"], item["claim_id"])),
        "wait_attempt_count": outcome_counts.get("WAIT", 0),
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
            "reasons": _top_counts(broad_reasons),
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
        "claim_duration_seconds": metrics["claim_duration_seconds"],
        "wait_episodes": metrics["wait_episodes"],
        "top_contention": metrics["top_contention"],
        "recovery_event_count": metrics["outcome_counts"].get("RECOVER", 0),
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
        temporary.write_bytes(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_validated_archive(path: Path, compressed: bytes, expected_raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(compressed)
        if os.environ.get("AGENT_CLAIM_TEST_FAIL_ARCHIVE_BEFORE_VALIDATE") == "1":
            raise OSError("simulated interruption before archive validation")
        if gzip.decompress(temporary.read_bytes()) != expected_raw:
            raise ValueError(f"Archive validation failed for {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _maintain_journal(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    common_directory = _git_common_directory(repository)
    if args.hot_days < 1:
        _print_result("INVALID_HOT_DAYS", hot_days=args.hot_days)
        return ERROR
    _root, hot_directory, archive_directory, journal_directory = _journal_paths(common_directory)
    cutoff = _now().date() - timedelta(days=args.hot_days - 1)
    archived: list[dict[str, Any]] = []
    try:
        with _maintenance_lock(common_directory):
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
    durations = metrics["claim_duration_seconds"]
    return "\n".join(
        (
            f"Claim report {report['window']['start']} to {report['window']['end']}",
            f"Events: {report['event_count']}",
            "Acquisitions: "
            f"primary={acquisitions['primary']} isolated={acquisitions['isolated']} recovery={acquisitions['recovery']}",
            f"Wait attempts: {metrics['wait_attempt_count']} in {len(metrics['wait_episodes'])} episodes",
            "Claim duration seconds: "
            f"median={durations['median']} p95={durations['p95']} maximum={durations['maximum']}",
            f"Open claims: {', '.join(metrics['open_claim_ids']) or 'none'}",
            f"Coverage gaps: {len(report['coverage_gaps'])}",
        )
    )


def _report(args: argparse.Namespace) -> int:
    repository = _repository_root(Path(args.repo).resolve())
    common_directory = _git_common_directory(repository)
    try:
        delta = _since_delta(args.since)
    except ValueError as error:
        _print_result("INVALID_SINCE", message=str(error))
        return ERROR
    end = _now()
    start = end - delta
    events, coverage_gaps = _load_events(common_directory)
    filtered = [event for event in events if start <= _parse_timestamp(str(event["timestamp"])) <= end]
    with _locked_registry(repository) as (_registry_path, data):
        live_claims = [dict(claim) for claim in data["claims"]]
    acquired_claim_ids = {
        str(event.get("claim_id"))
        for event in events
        if event.get("outcome") in {"PRIMARY", "ISOLATE", "RECOVER"}
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
    parser.add_argument("--all-files", action="store_true", help="Claim the complete repository file tree.")
    parser.add_argument("--resource", action="append", default=[], help="Exclusive repository-global runtime resource.")
    parser.add_argument("--scope-reason", help="Bounded coordination-only reason required for tree or all-files scope.")
    parser.add_argument(
        "--compat-file-directories",
        action="store_true",
        help="Temporarily convert existing directories passed through --file into warned tree scopes.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Coordinate repository claims, worktrees, and claim diagnostics.")
    parser.add_argument("--repo", default=".", help="Path inside the repository.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    acquire = subparsers.add_parser("acquire", help="Atomically acquire primary, isolated, or recovery ownership.")
    acquire.add_argument("--claim-id", required=True)
    acquire.add_argument("--agent", required=True)
    acquire.add_argument("--task", required=True)
    acquire.add_argument("--root-task-id", required=True)
    acquire.add_argument("--parent-claim-id")
    _add_scope_arguments(acquire)
    acquire.add_argument("--branch")
    acquire.add_argument("--worktree-path")
    acquire.add_argument("--base", default="HEAD")
    acquire.add_argument("--allow-recovery", action="store_true")
    acquire.set_defaults(handler=_acquire)

    extend = subparsers.add_parser("extend", help="Atomically add files, trees, or resources to an active claim.")
    extend.add_argument("--claim-id", required=True)
    _add_scope_arguments(extend)
    extend.set_defaults(handler=_extend)

    heartbeat = subparsers.add_parser("heartbeat", help="Refresh an active claim heartbeat.")
    heartbeat.add_argument("--claim-id", required=True)
    heartbeat.set_defaults(handler=_heartbeat)

    release = subparsers.add_parser("release", help="Release a committed clean claim or a declared no-change claim.")
    release.add_argument("--claim-id", required=True)
    release.add_argument("--no-change", action="store_true")
    release.set_defaults(handler=_release)

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
    return args.handler(args)


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
        exit_code = args.handler(args)
    finally:
        _RESULT_SINK.reset(token)
    if len(captured) != 1:
        raise ValueError(
            f"Claim command emitted {len(captured)} structured results; expected exactly one."
        )
    return captured[0], exit_code


if __name__ == "__main__":
    raise SystemExit(main())
