# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies read-only checkpoint-scoped Markdown checks through real MCP stdio.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _initialize(repository: Path) -> None:
    repository.mkdir()
    docs = repository / "docs"
    docs.mkdir()
    files = {
        "index.md": "[renamed](target.md)\n[deleted](deleted.md)\n",
        "target.md": "# Target\n",
        "deleted.md": "# Deleted\n",
        "modified.md": "# Original\n",
        "pre-existing.md": "# Clean\n",
        "staged.md": "# Staged baseline\n",
        "unstaged.md": "# Unstaged baseline\n",
    }
    for name, content in files.items():
        (docs / name).write_text(content, encoding="utf-8")
    _git(repository, "init")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "config", "user.name", "MCP Test")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "baseline")


def _repository_state(repository: Path) -> tuple[object, ...]:
    """Capture all repository evidence that a read-only MCP call must preserve."""
    paths = sorted(
        path for path in repository.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repository).parts
    )
    files = tuple(
        (
            path.relative_to(repository).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
            stat.S_IMODE(path.stat().st_mode),
        )
        for path in paths
    )
    return (
        _git(repository, "rev-parse", "HEAD"),
        _git(repository, "ls-files", "--stage"),
        _git(repository, "diff", "--cached", "--binary"),
        _git(repository, "diff", "--binary"),
        _git(repository, "ls-files", "--others", "--exclude-standard"),
        files,
    )


async def _read_only_call(
    client: Client,
    repository: Path,
    tool: str,
    arguments: dict[str, object],
) -> Any:
    """Invoke one endpoint and assert byte, mode, worktree, index, and HEAD stability."""
    before = _repository_state(repository)
    result = await client.call_tool(tool, arguments)
    assert _repository_state(repository) == before
    return result


async def _read_only_error(
    client: Client,
    repository: Path,
    tool: str,
    arguments: dict[str, object],
) -> ToolError:
    """Invoke one failing endpoint and assert that the repository remains unchanged."""
    before = _repository_state(repository)
    try:
        await client.call_tool(tool, arguments)
    except ToolError as error:
        assert _repository_state(repository) == before
        return error
    raise AssertionError(f"{tool} should have failed.")


async def test_checkpoint_and_git_changed_scopes_are_read_only_over_stdio(tmp_path: Path) -> None:
    """Exercise all changed-file states and checkpoint failures through real stdio."""
    repository = tmp_path / "repository"
    other_repository = tmp_path / "other-repository"
    _initialize(repository)
    _initialize(other_repository)
    docs = repository / "docs"
    (docs / "pre-existing.md").write_text("# Dirty before capture\n", encoding="utf-8")

    environment = os.environ.copy()
    environment["MCP_AGENT_OPS_WORKSPACE_ROOTS"] = str(tmp_path)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "mcp_agent_ops"],
        env=environment,
        cwd=str(tmp_path),
    )

    async with Client(transport, timeout=20) as client:
        captured = await _read_only_call(
            client,
            repository,
            "capture_repository_state",
            {"repository_root": str(repository)},
        )
        checkpoint_id = captured.structured_content["checkpoint_id"]

        (docs / "modified.md").write_text("# Modified after capture\n", encoding="utf-8")
        (docs / "target.md").rename(docs / "renamed target.md")
        (docs / "deleted.md").unlink()
        (docs / "new ünicode file.md").write_text("# Added\n", encoding="utf-8")

        checkpoint_result = await _read_only_call(
            client,
            repository,
            "verify_markdown_links",
            {
                "repository_root": str(repository),
                "scope": "changed_since_checkpoint",
                "checkpoint_id": checkpoint_id,
            },
        )
        result = checkpoint_result.structured_content
        assert result["scope"] == "changed_since_checkpoint"
        assert result["checkpoint_id"] == checkpoint_id
        assert result["added_files"] == ["docs/new ünicode file.md"]
        assert result["modified_files"] == ["docs/modified.md"]
        assert result["renamed_files"] == [
            {"old_path": "docs/target.md", "new_path": "docs/renamed target.md"}
        ]
        assert result["deleted_files"] == ["docs/deleted.md"]
        assert "docs/pre-existing.md" not in result["selected_files"]
        assert result["affected_inbound_files"] == ["docs/index.md"]
        assert {finding["target"] for finding in result["findings"]} == {
            "target.md",
            "deleted.md",
        }

        _git(repository, "add", "docs/modified.md")
        (docs / "unstaged.md").write_text("# Unstaged change\n", encoding="utf-8")
        (docs / "untracked file.md").write_text("# Untracked\n", encoding="utf-8")
        git_result = await _read_only_call(
            client,
            repository,
            "verify_markdown_links",
            {"repository_root": str(repository), "scope": "git_changed"},
        )
        git_content = git_result.structured_content
        assert "docs/pre-existing.md" in git_content["modified_files"]
        assert "docs/modified.md" in git_content["modified_files"]
        assert "docs/unstaged.md" in git_content["modified_files"]
        assert "docs/untracked file.md" in git_content["added_files"]
        assert git_content["renamed_files"] == [
            {"old_path": "docs/target.md", "new_path": "docs/renamed target.md"}
        ]
        assert git_content["deleted_files"] == ["docs/deleted.md"]

        empty_checkpoint = await _read_only_call(
            client,
            repository,
            "capture_repository_state",
            {"repository_root": str(repository)},
        )
        empty_result = await _read_only_call(
            client,
            repository,
            "verify_markdown_links",
            {
                "repository_root": str(repository),
                "scope": "changed_since_checkpoint",
                "checkpoint_id": empty_checkpoint.structured_content["checkpoint_id"],
            },
        )
        assert empty_result.structured_content["ok"] is True
        assert empty_result.structured_content["selected_files"] == []
        assert empty_result.structured_content["checked_files"] == []

        missing = await _read_only_call(
            client,
            repository,
            "verify_markdown_links",
            {
                "repository_root": str(repository),
                "patterns": ["docs/missing.md", "docs/no-match-*.md"],
            },
        )
        assert missing.structured_content["findings"][0]["code"] == "requested_path_missing"
        assert missing.structured_content["unmatched_patterns"] == ["docs/no-match-*.md"]

        wrong_repository = await _read_only_error(
            client,
            other_repository,
            "verify_markdown_links",
            {
                "repository_root": str(other_repository),
                "scope": "changed_since_checkpoint",
                "checkpoint_id": checkpoint_id,
            },
        )
        assert "another repository or worktree" in str(wrong_repository)

        missing_checkpoint = await _read_only_error(
            client,
            repository,
            "verify_markdown_links",
            {
                "repository_root": str(repository),
                "scope": "changed_since_checkpoint",
                "checkpoint_id": "expired-checkpoint",
            },
        )
        assert "missing or expired" in str(missing_checkpoint)

        ambiguous = await _read_only_error(
            client,
            repository,
            "verify_markdown_links",
            {
                "repository_root": str(repository),
                "scope": "git_changed",
                "patterns": ["docs/*.md"],
            },
        )
        assert "cannot be combined" in str(ambiguous)
