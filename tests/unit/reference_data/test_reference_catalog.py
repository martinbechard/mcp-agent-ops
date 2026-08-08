# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies safe direct-file discovery and ordered reference-data aggregation across scopes.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

import pytest

from mcp_agent_ops.reference_data.catalog import ReferenceCatalog


def test_catalog_aggregates_every_matching_scope_in_order(tmp_path: Path) -> None:
    """Combine project and configured sources without exposing their host paths."""
    project = tmp_path / "project"
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (project, first, second):
        root.mkdir()
    (project / "lexicon.txt").write_text("project term", encoding="utf-8")
    (first / "lexicon.txt").write_text("shared term", encoding="utf-8")
    (second / "lexicon.txt").write_text("user term", encoding="utf-8")

    catalog = ReferenceCatalog.from_scopes(
        project_root=project,
        roots=[first, second],
        allowed_names=["lexicon.txt"],
    )
    loaded = catalog.load(["lexicon.txt"])

    assert loaded.ok is True
    assert loaded.references[0].content == "project term\nshared term\nuser term"
    assert loaded.references[0].source_count == 3
    assert [source.scope for source in loaded.references[0].sources] == [
        "project",
        "configured:0",
        "configured:1",
    ]
    assert all(len(source.digest) == 64 for source in loaded.references[0].sources)
    assert "path" not in loaded.references[0].model_dump_json()


def test_catalog_discovers_only_direct_files_and_skips_missing_scopes(tmp_path: Path) -> None:
    """Ignore nested matches while retaining a direct match from another scope."""
    project = tmp_path / "project"
    shared = tmp_path / "shared"
    (project / "nested").mkdir(parents=True)
    shared.mkdir()
    (project / "nested" / "lexicon.txt").write_text("nested", encoding="utf-8")
    (shared / "lexicon.txt").write_text("shared", encoding="utf-8")

    catalog = ReferenceCatalog.from_scopes(
        project_root=project,
        roots=[shared],
        allowed_names=["lexicon.txt"],
    )

    assert catalog.load(["lexicon.txt"]).references[0].content == "shared"


def test_catalog_deduplicates_the_same_resolved_file(tmp_path: Path) -> None:
    """Do not repeat content when overlapping configured scopes resolve to one file."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "lexicon.txt").write_text("one copy", encoding="utf-8")

    loaded = ReferenceCatalog.from_scopes(
        project_root=shared,
        roots=[shared],
        allowed_names=["lexicon.txt"],
    ).load(["lexicon.txt"])

    assert loaded.references[0].content == "one copy"
    assert [source.scope for source in loaded.references[0].sources] == ["project"]


def test_catalog_snapshot_keeps_content_and_digest_paired(tmp_path: Path) -> None:
    """Require a replacement catalog before changed reference bytes become visible."""
    shared = tmp_path / "shared"
    shared.mkdir()
    reference = shared / "lexicon.txt"
    reference.write_text("first", encoding="utf-8")
    catalog = ReferenceCatalog.from_scopes(None, [shared], ["lexicon.txt"])
    original = catalog.load(["lexicon.txt"]).references[0]

    reference.write_text("second", encoding="utf-8")

    unchanged = catalog.load(["lexicon.txt"]).references[0]
    refreshed = ReferenceCatalog.from_scopes(None, [shared], ["lexicon.txt"])
    changed = refreshed.load(["lexicon.txt"]).references[0]
    assert unchanged.content == original.content
    assert unchanged.digest == original.digest
    assert changed.content == "second"
    assert changed.digest != original.digest
    assert refreshed.public_result().revision != catalog.public_result().revision


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", ".env", "nested/lexicon.txt", r"nested\lexicon.txt"],
)
def test_catalog_rejects_unsafe_allowed_names(tmp_path: Path, name: str) -> None:
    """Keep configuration from authorizing traversal or hidden project files."""
    with pytest.raises(ValueError, match="safe direct filename"):
        ReferenceCatalog.from_scopes(tmp_path, [], [name])


def test_catalog_rejects_symlink_escape_and_non_utf8_content(tmp_path: Path) -> None:
    """Recheck containment and text decoding at the reference read boundary."""
    shared = tmp_path / "shared"
    outside = tmp_path / "outside"
    shared.mkdir()
    outside.mkdir()
    (outside / "lexicon.txt").write_text("private", encoding="utf-8")
    (shared / "lexicon.txt").symlink_to(outside / "lexicon.txt")

    with pytest.raises(ValueError, match="outside its configured scope"):
        ReferenceCatalog.from_scopes(None, [shared], ["lexicon.txt"])

    (shared / "lexicon.txt").unlink()
    (shared / "lexicon.txt").write_bytes(b"\xff")
    with pytest.raises(UnicodeError):
        ReferenceCatalog.from_scopes(None, [shared], ["lexicon.txt"])


def test_catalog_load_is_bounded_ordered_and_all_or_nothing(tmp_path: Path) -> None:
    """Return no partial content for invalid, duplicate, missing, or unallowed requests."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "alpha.txt").write_text("alpha", encoding="utf-8")
    (shared / "beta.txt").write_text("beta", encoding="utf-8")
    catalog = ReferenceCatalog.from_scopes(
        None,
        [shared],
        ["alpha.txt", "beta.txt", "missing.txt"],
    )

    loaded = catalog.load(["beta.txt", "alpha.txt"])
    assert loaded.ok is True
    assert [reference.name for reference in loaded.references] == [
        "beta.txt",
        "alpha.txt",
    ]

    duplicate = catalog.load(["alpha.txt", "alpha.txt"])
    assert duplicate.ok is False
    assert duplicate.references == []
    assert duplicate.errors[0].code == "duplicate_reference"

    missing = catalog.load(["alpha.txt", "missing.txt"])
    assert missing.ok is False
    assert missing.references == []
    assert missing.errors[0].code == "reference_not_found"

    unallowed = catalog.load(["private.txt"])
    assert unallowed.ok is False
    assert unallowed.references == []
    assert unallowed.errors[0].code == "reference_not_allowed"

    invalid = catalog.load(["../private.txt"])
    assert invalid.ok is False
    assert invalid.references == []
    assert invalid.errors[0].code == "invalid_reference_name"


def test_catalog_rejects_non_files_and_oversized_loads(tmp_path: Path) -> None:
    """Reject an invalid direct candidate and enforce the aggregate response limit."""
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "directory.txt").mkdir()
    with pytest.raises(ValueError, match="regular file"):
        ReferenceCatalog.from_scopes(None, [shared], ["directory.txt"])

    (shared / "large.txt").write_text("x" * (1024 * 1024 + 1), encoding="utf-8")
    catalog = ReferenceCatalog.from_scopes(None, [shared], ["large.txt"])
    loaded = catalog.load(["large.txt"])
    assert loaded.ok is False
    assert loaded.references == []
    assert loaded.errors[0].code == "content_limit_exceeded"
