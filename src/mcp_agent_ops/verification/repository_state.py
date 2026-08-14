# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Captures and compares read-only Git repository and filesystem checkpoints.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileState:
    """Identify one Git-visible path without retaining its file content.

    The digest and executable mode distinguish content and permission changes. Missing
    tracked paths remain represented so a later recreation can be detected.
    """

    digest: str | None
    mode: int | None


@dataclass(frozen=True)
class RepositoryCheckpoint:
    """Hold one process-local, repository-bound read snapshot.

    Checkpoints are immutable and valid only in the server process that captured them.
    """

    checkpoint_id: str
    repository_root: Path
    repository_identity: str
    files: dict[str, FileState]


@dataclass(frozen=True)
class RepositoryChanges:
    """Describe deterministic path changes between repository states."""

    added: list[str]
    modified: list[str]
    renamed: list[tuple[str, str]]
    deleted: list[str]


def _git(repository_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(message or "Repository state could not be read with Git.")
    return completed.stdout


def _repository_identity(repository_root: Path) -> str:
    common_dir = _git(repository_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(os.fsdecode(common_dir).strip()).resolve())


def _visible_paths(repository_root: Path) -> list[str]:
    output = _git(
        repository_root,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    )
    return sorted({os.fsdecode(value) for value in output.split(b"\0") if value})


def _file_state(repository_root: Path, relative_path: str) -> FileState:
    path = repository_root / relative_path
    try:
        stat = path.stat()
    except FileNotFoundError:
        return FileState(digest=None, mode=None)
    if not path.is_file():
        return FileState(digest=None, mode=stat.st_mode & 0o777)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return FileState(digest=digest, mode=stat.st_mode & 0o777)


def snapshot_repository(repository_root: Path) -> tuple[str, dict[str, FileState]]:
    """Read the repository identity and Git-visible filesystem state.

    Args:
        repository_root: Absolute root of an existing Git worktree.

    Returns:
        The repository-global Git identity and every tracked or untracked file state.

    Raises:
        ValueError: If Git cannot identify or enumerate the repository.

    The operation reads Git and file content but never writes the worktree or index.
    """
    root = repository_root.resolve()
    return _repository_identity(root), {
        path: _file_state(root, path) for path in _visible_paths(root)
    }


def compare_repository_states(
    before: dict[str, FileState],
    after: dict[str, FileState],
) -> RepositoryChanges:
    """Compare two snapshots and pair exact-content moves as renames."""
    added = {path for path in after.keys() - before.keys() if after[path].digest is not None}
    deleted = {path for path in before.keys() - after.keys() if before[path].digest is not None}
    added.update(
        path for path in before.keys() & after.keys()
        if before[path].digest is None and after[path].digest is not None
    )
    deleted.update(
        path for path in before.keys() & after.keys()
        if before[path].digest is not None and after[path].digest is None
    )
    modified = sorted(
        path for path in before.keys() & after.keys()
        if before[path].digest is not None
        and after[path].digest is not None
        and before[path] != after[path]
    )

    deleted_by_state: dict[FileState, list[str]] = {}
    for path in deleted:
        deleted_by_state.setdefault(before[path], []).append(path)
    renamed: list[tuple[str, str]] = []
    for new_path in sorted(added):
        matches = deleted_by_state.get(after[new_path], [])
        if len(matches) == 1:
            old_path = matches.pop()
            renamed.append((old_path, new_path))
            deleted.remove(old_path)
            added.remove(new_path)

    return RepositoryChanges(
        added=sorted(added),
        modified=modified,
        renamed=renamed,
        deleted=sorted(deleted),
    )


def git_changed_files(repository_root: Path) -> RepositoryChanges:
    """Derive all current tracked and untracked checkout changes from Git.

    Args:
        repository_root: Absolute root of an existing Git worktree.

    Returns:
        Added, modified, renamed, deleted, and untracked paths relative to the root.

    Raises:
        ValueError: If Git cannot inspect the repository.

    The operation invokes only read-only Git commands.
    """
    root = repository_root.resolve()
    head: dict[str, FileState] = {}
    for entry in _git(root, "ls-tree", "-r", "-z", "HEAD").split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        raw_mode, object_type, object_id = metadata.split(b" ", 2)
        if object_type != b"blob":
            continue
        content = _git(root, "cat-file", "blob", os.fsdecode(object_id))
        head[os.fsdecode(raw_path)] = FileState(
            digest=hashlib.sha256(content).hexdigest(),
            mode=int(raw_mode, 8) & 0o777,
        )
    _, current = snapshot_repository(root)
    return compare_repository_states(head, current)


class RepositoryCheckpointStore:
    """Own immutable checkpoints for one MCP server process.

    Typical usage captures before a bounded operation and compares after it. Checkpoint
    identifiers are opaque, are rejected for other repositories, and expire on process exit.
    """

    def __init__(self) -> None:
        self._checkpoints: dict[str, RepositoryCheckpoint] = {}

    def capture(self, repository_root: Path) -> RepositoryCheckpoint:
        """Capture a new read-only checkpoint for an existing Git repository."""
        root = repository_root.resolve()
        identity, files = snapshot_repository(root)
        checkpoint = RepositoryCheckpoint(uuid.uuid4().hex, root, identity, files)
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        return checkpoint

    def changes_since(self, repository_root: Path, checkpoint_id: str) -> RepositoryChanges:
        """Compare a repository with its matching process-local checkpoint.

        Raises:
            ValueError: If the identifier is missing, expired, repository-mismatched, or
                the current state cannot be reconciled.
        """
        checkpoint = self._checkpoints.get(checkpoint_id)
        if checkpoint is None:
            raise ValueError("Checkpoint is missing or expired in this MCP server process.")
        root = repository_root.resolve()
        identity, current = snapshot_repository(root)
        if root != checkpoint.repository_root or identity != checkpoint.repository_identity:
            raise ValueError("Checkpoint belongs to another repository or worktree.")
        return compare_repository_states(checkpoint.files, current)
