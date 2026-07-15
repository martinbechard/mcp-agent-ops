# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies structured YAML syntax and duplicate-key diagnostics.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

from mcp_agent_ops.verification.yaml_files import verify_yaml


def test_verify_yaml_reports_duplicate_mapping_keys_with_location(tmp_path: Path) -> None:
    source = tmp_path / "PROJECT.yaml"
    source.write_text("name: first\nname: second\n", encoding="utf-8")

    result = verify_yaml(tmp_path, ["PROJECT.yaml"])

    assert result.ok is False
    assert result.checked_files == ["PROJECT.yaml"]
    assert [(finding.code, finding.path, finding.line) for finding in result.findings] == [
        ("duplicate_key", "PROJECT.yaml", 2)
    ]


def test_verify_yaml_accepts_valid_files_and_reports_missing_inputs(tmp_path: Path) -> None:
    (tmp_path / "valid.yaml").write_text("project:\n  enabled: true\n", encoding="utf-8")

    result = verify_yaml(tmp_path, ["valid.yaml", "missing.yaml"])

    assert result.ok is False
    assert result.checked_files == ["valid.yaml"]
    assert [(finding.code, finding.path) for finding in result.findings] == [
        ("file_not_found", "missing.yaml")
    ]


def test_verify_yaml_rejects_paths_outside_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.yaml"
    outside.write_text("safe: true\n", encoding="utf-8")

    result = verify_yaml(tmp_path, ["../outside.yaml"])

    assert result.ok is False
    assert result.checked_files == []
    assert result.findings[0].code == "path_outside_root"
