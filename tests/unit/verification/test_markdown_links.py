# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies deterministic local Markdown link and anchor checks.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

from mcp_agent_ops.verification.markdown_links import verify_markdown_links


def test_verify_markdown_links_checks_local_targets_and_ignores_remote_urls(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\n## Setup Steps\n", encoding="utf-8")
    (docs / "index.md").write_text(
        "[guide](guide.md#setup-steps)\n[remote](https://example.com)\n[mail](mailto:test@example.invalid)\n",
        encoding="utf-8",
    )

    result = verify_markdown_links(tmp_path, ["docs/**/*.md"])

    assert result.ok is True
    assert result.checked_files == ["docs/guide.md", "docs/index.md"]
    assert result.findings == []


def test_verify_markdown_links_reports_missing_files_and_anchors(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (docs / "index.md").write_text(
        "[missing](missing.md)\n[anchor](guide.md#not-present)\n",
        encoding="utf-8",
    )

    result = verify_markdown_links(tmp_path, ["docs/**/*.md"])

    assert result.ok is False
    assert [(finding.code, finding.target) for finding in result.findings] == [
        ("missing_target", "missing.md"),
        ("missing_anchor", "guide.md#not-present"),
    ]


def test_verify_markdown_links_rejects_source_patterns_outside_root(tmp_path: Path) -> None:
    result = verify_markdown_links(tmp_path, ["../*.md"])

    assert result.ok is False
    assert result.checked_files == []
    assert result.findings[0].code == "path_outside_root"

