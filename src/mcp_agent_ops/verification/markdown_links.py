# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies local Markdown link targets and heading anchors within a trusted root.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import unquote, urlsplit

from mcp_agent_ops.verification.models import VerificationFinding, VerificationReport
from mcp_agent_ops.verification.paths import PathBoundaryError, resolve_within_root, validate_glob_pattern

LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


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


def _link_destination(raw: str) -> str:
    value = raw.strip()
    if value.startswith("<") and ">" in value:
        return value[1:value.index(">")]
    if " " in value:
        return value.split(" ", 1)[0]
    return value


def verify_markdown_links(root: Path, patterns: Sequence[str]) -> VerificationReport:
    """Check local Markdown file and anchor links selected by root-relative globs.

    Args:
        root: Trusted repository or documentation root.
        patterns: Root-relative glob expressions selecting Markdown source files.

    Returns:
        A report of checked source files and missing targets, missing anchors,
        decoding failures, or paths that attempt to escape `root`.

    Remote, mail, and data links are deliberately ignored; the function performs no
    network access or filesystem mutation.
    """
    resolved_root = root.resolve()
    findings: list[VerificationFinding] = []
    selected: set[Path] = set()
    text_cache: dict[Path, str] = {}
    anchor_cache: dict[Path, set[str]] = {}

    def read_text(path: Path) -> str:
        if path not in text_cache:
            text_cache[path] = path.read_text(encoding="utf-8")
        return text_cache[path]

    def anchors(path: Path) -> set[str]:
        if path not in anchor_cache:
            anchor_cache[path] = _anchors(read_text(path))
        return anchor_cache[path]

    for pattern in dict.fromkeys(patterns):
        try:
            validate_glob_pattern(pattern)
        except PathBoundaryError as error:
            findings.append(VerificationFinding(code="path_outside_root", message=str(error), path=pattern))
            continue
        selected.update(path.resolve() for path in resolved_root.glob(pattern) if path.is_file())

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
                            message="Markdown heading anchor does not exist.",
                            path=relative_source,
                            target=destination,
                        )
                    )
    return VerificationReport(ok=not findings, checked_files=checked, findings=findings)
