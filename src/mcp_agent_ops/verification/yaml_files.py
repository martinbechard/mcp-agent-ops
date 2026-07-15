# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Validates YAML inputs and reports duplicate mapping keys with source locations.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode

from mcp_agent_ops.verification.models import VerificationFinding, VerificationReport
from mcp_agent_ops.verification.paths import PathBoundaryError, resolve_within_root


class DuplicateKeyError(ValueError):
    """Carry the source position of a duplicate YAML mapping key."""

    def __init__(self, key: object, line: int, column: int) -> None:
        super().__init__(f"Duplicate YAML mapping key: {key}")
        self.line = line
        self.column = column


class UniqueKeyLoader(yaml.SafeLoader):
    """Load YAML safely while rejecting duplicate keys instead of overwriting them."""


def _construct_mapping(loader: UniqueKeyLoader, node: MappingNode, deep: bool = False) -> dict[object, Any]:
    loader.flatten_mapping(node)
    result: dict[object, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise DuplicateKeyError(key, key_node.start_mark.line + 1, key_node.start_mark.column + 1)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def verify_yaml(root: Path, paths: Sequence[str]) -> VerificationReport:
    """Validate requested YAML files without mutating the inspected repository.

    Args:
        root: Trusted repository or workspace root.
        paths: Exact absolute or root-relative YAML file paths.

    Returns:
        A complete report containing every checked file and syntax, duplicate-key,
        missing-file, decoding, or path-boundary finding.
    """
    resolved_root = root.resolve()
    checked: list[str] = []
    findings: list[VerificationFinding] = []
    for value in dict.fromkeys(paths):
        try:
            path = resolve_within_root(resolved_root, value)
        except PathBoundaryError as error:
            findings.append(VerificationFinding(code="path_outside_root", message=str(error), path=value))
            continue
        relative = path.relative_to(resolved_root).as_posix()
        if not path.is_file():
            findings.append(
                VerificationFinding(code="file_not_found", message="YAML file does not exist.", path=relative)
            )
            continue
        checked.append(relative)
        try:
            yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        except DuplicateKeyError as error:
            findings.append(
                VerificationFinding(
                    code="duplicate_key",
                    message=str(error),
                    path=relative,
                    line=error.line,
                    column=error.column,
                )
            )
        except yaml.MarkedYAMLError as error:
            mark = error.problem_mark
            findings.append(
                VerificationFinding(
                    code="yaml_syntax",
                    message=error.problem or str(error),
                    path=relative,
                    line=mark.line + 1 if mark else None,
                    column=mark.column + 1 if mark else None,
                )
            )
        except UnicodeDecodeError as error:
            findings.append(
                VerificationFinding(code="invalid_utf8", message=str(error), path=relative)
            )
    return VerificationReport(ok=not findings, checked_files=checked, findings=findings)
