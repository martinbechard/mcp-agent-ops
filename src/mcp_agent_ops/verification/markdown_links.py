# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies local Markdown link targets, heading anchors, and HTML IDs within a trusted root.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import re
from collections import Counter
from collections.abc import Sequence
from glob import has_magic
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from mcp_agent_ops.verification.models import VerificationFinding, VerificationReport
from mcp_agent_ops.verification.paths import PathBoundaryError, resolve_within_root, validate_glob_pattern
from mcp_agent_ops.verification.repository_state import RepositoryChanges

LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
HTML_SUFFIXES = {".htm", ".html"}


class _HTMLIDParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag
        self.ids.update(value for name, value in attrs if name == "id" and value is not None)


def _slug(value: str) -> str:
    without_markup = re.sub(r"[`*_~]", "", value).strip().lower()
    without_punctuation = re.sub(r"[^\w\- ]", "", without_markup)
    return re.sub(r"[\s\-]+", "-", without_punctuation).strip("-")


def _anchors(text: str) -> set[str]:
    counts: Counter[str] = Counter()
    anchors: set[str] = set()
    for heading in HEADING_PATTERN.findall(text):
        base = _slug(heading)
        suffix = counts[base]
        anchors.add(base if suffix == 0 else f"{base}-{suffix}")
        counts[base] += 1
    return anchors


def _html_ids(text: str) -> set[str]:
    parser = _HTMLIDParser()
    try:
        parser.feed(text)
        parser.close()
    except AssertionError:
        # HTMLParser asserts on some malformed declarations; retain IDs parsed before the failure.
        pass
    return parser.ids


def _link_destination(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1:value.index(">")]
    if " " in value:
        return value.split(" ", 1)[0]
    return value


def _inbound_sources(root: Path, targets: set[str]) -> list[str]:
    """Find current Markdown files whose local destinations resolve to changed targets."""
    affected: set[str] = set()
    for source in root.rglob("*.md"):
        if not source.is_file() or ".git" in source.relative_to(root).parts:
            continue
        try:
            text = source.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for raw in LINK_PATTERN.findall(text):
            destination = _link_destination(raw)
            parsed = urlsplit(destination)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            try:
                target = resolve_within_root(root, str(source.parent / unquote(parsed.path)))
            except PathBoundaryError:
                continue
            if target.relative_to(root).as_posix() in targets:
                affected.add(source.relative_to(root).as_posix())
                break
    return sorted(affected)


def verify_markdown_links(
    root: Path,
    patterns: Sequence[str] | None = None,
    *,
    scope: str = "patterns",
    checkpoint_id: str | None = None,
    changes: RepositoryChanges | None = None,
) -> VerificationReport:
    """Check local Markdown links selected explicitly or from repository changes.

    Args:
        root: Trusted repository or documentation root.
        patterns: Root-relative exact paths or glob expressions in ``patterns`` scope.
        scope: ``patterns``, ``git_changed``, or ``changed_since_checkpoint``.
        checkpoint_id: Opaque checkpoint identifier included in checkpoint-scoped results.
        changes: Server-derived repository changes for either changed-file scope.

    Returns:
        A report distinguishing selection, changed paths, unmatched patterns, checked
        files, inbound references, and link findings.

    Raises:
        ValueError: If the scope or combination of arguments is ambiguous.

    Remote, mail, and data links are deliberately ignored; the function performs no
    network access or filesystem mutation.
    """
    resolved_root = root.resolve()
    findings: list[VerificationFinding] = []
    selected: set[Path] = set()
    unmatched_patterns: list[str] = []
    text_cache: dict[Path, str] = {}
    anchor_cache: dict[Path, set[str]] = {}

    if scope not in {"patterns", "git_changed", "changed_since_checkpoint"}:
        raise ValueError(f"Unsupported Markdown verification scope: {scope}")
    if scope == "patterns" and changes is not None:
        raise ValueError("Pattern scope cannot receive repository changes.")
    if scope != "patterns" and patterns is not None:
        raise ValueError("Caller-supplied patterns cannot be combined with a changed-file scope.")
    if scope != "patterns" and changes is None:
        raise ValueError("Changed-file scope requires server-derived repository changes.")
    if scope == "changed_since_checkpoint" and not checkpoint_id:
        raise ValueError("changed_since_checkpoint scope requires checkpoint_id.")
    if scope != "changed_since_checkpoint" and checkpoint_id is not None:
        raise ValueError("checkpoint_id is valid only with changed_since_checkpoint scope.")

    def read_text(path: Path) -> str:
        if path not in text_cache:
            text_cache[path] = path.read_text(encoding="utf-8")
        return text_cache[path]

    def anchors(path: Path) -> set[str]:
        if path not in anchor_cache:
            text = read_text(path)
            anchor_cache[path] = _html_ids(text) if path.suffix.lower() in HTML_SUFFIXES else _anchors(text)
        return anchor_cache[path]

    added_files: list[str] = []
    modified_files: list[str] = []
    renamed_files: list[dict[str, str]] = []
    deleted_files: list[str] = []
    affected_inbound_files: list[str] = []
    if scope == "patterns":
        for pattern in dict.fromkeys(patterns or ["**/*.md"]):
            try:
                validate_glob_pattern(pattern)
            except PathBoundaryError as error:
                findings.append(VerificationFinding(code="path_outside_root", message=str(error), path=pattern))
                continue
            matches = [path.resolve() for path in resolved_root.glob(pattern) if path.is_file()]
            if not matches:
                if has_magic(pattern):
                    unmatched_patterns.append(pattern)
                else:
                    findings.append(
                        VerificationFinding(
                            code="requested_path_missing",
                            message="Exact requested Markdown source file does not exist.",
                            path=pattern,
                        )
                    )
            selected.update(matches)
    else:
        assert changes is not None
        added_files = changes.added
        modified_files = changes.modified
        renamed_files = [{"old_path": old, "new_path": new} for old, new in changes.renamed]
        deleted_files = changes.deleted
        current_changed = [*changes.added, *changes.modified, *(new for _, new in changes.renamed)]
        for relative_path in current_changed:
            if Path(relative_path).suffix.lower() == ".md":
                source = resolve_within_root(resolved_root, relative_path)
                if source.is_file():
                    selected.add(source)
        old_targets = {*changes.deleted, *(old for old, _ in changes.renamed)}
        if old_targets:
            affected_inbound_files = _inbound_sources(resolved_root, old_targets)
            selected.update(resolved_root / path for path in affected_inbound_files)

    checked: list[str] = []
    for source in sorted(selected):
        try:
            source = resolve_within_root(resolved_root, str(source))
        except PathBoundaryError as error:
            findings.append(VerificationFinding(code="path_outside_root", message=str(error), path=str(source)))
            continue
        relative_source = source.relative_to(resolved_root).as_posix()
        checked.append(relative_source)
        try:
            text = read_text(source)
        except UnicodeDecodeError as error:
            findings.append(VerificationFinding(code="invalid_utf8", message=str(error), path=relative_source))
            continue
        for raw in LINK_PATTERN.findall(text):
            destination = _link_destination(raw)
            parsed = urlsplit(destination)
            if parsed.scheme or parsed.netloc:
                continue
            target_path_text = unquote(parsed.path)
            target = source if not target_path_text else (source.parent / target_path_text)
            try:
                target = resolve_within_root(resolved_root, str(target))
            except PathBoundaryError as error:
                findings.append(
                    VerificationFinding(
                        code="path_outside_root",
                        message=str(error),
                        path=relative_source,
                        target=destination,
                    )
                )
                continue
            if not target.exists():
                findings.append(
                    VerificationFinding(
                        code="missing_target",
                        message="Local Markdown link target does not exist.",
                        path=relative_source,
                        target=destination,
                    )
                )
                continue
            if parsed.fragment and target.is_file():
                try:
                    target_anchors = anchors(target)
                except UnicodeDecodeError as error:
                    findings.append(
                        VerificationFinding(code="invalid_utf8", message=str(error), path=relative_source)
                    )
                    continue
                if unquote(parsed.fragment) not in target_anchors:
                    findings.append(
                        VerificationFinding(
                            code="missing_anchor",
                            message=(
                                "HTML ID anchor does not exist."
                                if target.suffix.lower() in HTML_SUFFIXES
                                else "Markdown heading anchor does not exist."
                            ),
                            path=relative_source,
                            target=destination,
                        )
                    )
    selected_files: list[str] = []
    for path in sorted(selected):
        try:
            selected_files.append(path.relative_to(resolved_root).as_posix())
        except ValueError:
            continue
    return VerificationReport(
        ok=not findings and not unmatched_patterns,
        scope=scope,
        checkpoint_id=checkpoint_id,
        selected_files=selected_files,
        added_files=added_files,
        modified_files=modified_files,
        renamed_files=renamed_files,
        deleted_files=deleted_files,
        checked_files=checked,
        affected_inbound_files=affected_inbound_files,
        unmatched_patterns=unmatched_patterns,
        findings=findings,
    )
