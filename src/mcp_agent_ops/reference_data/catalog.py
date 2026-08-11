# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Loads recursive text references from authorized folders into immutable aggregations.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mcp_agent_ops.reference_data.models import (
    AggregatedReference,
    PublishedReferenceCatalog,
    ReferenceLoadError,
    ReferenceLoadResult,
    ReferenceSourceMetadata,
)

_MAX_BATCH_REFERENCES = 32
_MAX_BATCH_CONTENT_BYTES = 1024 * 1024
_MAX_SOURCES_PER_REFERENCE = 64


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _is_safe_name(name: str) -> bool:
    path = Path(name)
    return (
        bool(name)
        and name not in {".", ".."}
        and "\0" not in name
        and "\\" not in name
        and not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == name
    )


def _within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _revision(entries: dict[str, AggregatedReference]) -> str:
    payload = {
        "entries": [
            {
                "name": name,
                "digest": entries[name].digest,
                "sources": [source.digest for source in entries[name].sources],
            }
            for name in sorted(entries)
        ],
    }
    return _digest(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class ReferenceCatalog:
    """Own one immutable snapshot of recursive references beneath allowed roots.

    Use :meth:`from_scopes` with authorized project roots and administrator-configured
    reference roots. The resulting instance can service repeated model-facing loads while
    keeping content and digests paired until the caller builds a replacement snapshot.

    Example:
        ``ReferenceCatalog.from_scopes([project / ".agents"], [user / ".agents"])``
        publishes every safe UTF-8 file by its path relative to those roots.
    """

    def __init__(
        self,
        entries: dict[str, AggregatedReference],
    ) -> None:
        self._entries = {
            name: entry.model_copy(deep=True) for name, entry in entries.items()
        }
        self._revision = _revision(self._entries)

    @classmethod
    def from_scopes(
        cls,
        project_roots: list[Path],
        roots: list[Path],
    ) -> ReferenceCatalog:
        """Build a project-first snapshot from recursive UTF-8 files in every root.

        Args:
            project_roots: Authorized working-project folders searched first.
            roots: Administrator-configured reference roots searched in caller order.

        Returns:
            An immutable path-free catalog containing every available aggregation.

        Raises:
            OSError: If a matching reference cannot be read.
            ValueError: If a relative path has too many sources.
        """
        scopes = [
            (f"project:{index}", root.expanduser().resolve())
            for index, root in enumerate(project_roots)
        ]
        scopes.extend(
            (f"configured:{index}", root.expanduser().resolve())
            for index, root in enumerate(roots)
        )

        aggregated: dict[str, tuple[list[str], list[ReferenceSourceMetadata], set[Path]]] = {}
        for scope, root in scopes:
            if not root.is_dir():
                continue
            for candidate in root.rglob("*"):
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                if not _within_root(resolved, root):
                    continue
                name = candidate.relative_to(root).as_posix()
                if not _is_safe_name(name):
                    continue
                contents, sources, seen_paths = aggregated.setdefault(name, ([], [], set()))
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                content_bytes = resolved.read_bytes()
                try:
                    content = content_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                contents.append(content)
                sources.append(
                    ReferenceSourceMetadata(
                        scope=scope,
                        digest=_digest(content_bytes),
                        byte_count=len(content_bytes),
                    )
                )
                if len(sources) > _MAX_SOURCES_PER_REFERENCE:
                    raise ValueError(
                        f"Reference '{name}' has more than {_MAX_SOURCES_PER_REFERENCE} sources."
                    )

        entries: dict[str, AggregatedReference] = {}
        for name, (contents, sources, _) in aggregated.items():
            if sources:
                content = "\n".join(contents)
                entries[name] = AggregatedReference(
                    name=name,
                    digest=_digest(content.encode("utf-8")),
                    content=content,
                    source_count=len(sources),
                    sources=sources,
                )
        return cls(entries)

    def public_result(self) -> PublishedReferenceCatalog:
        """Return the current revision and available names without host paths."""
        return PublishedReferenceCatalog(
            revision=self._revision,
            names=sorted(self._entries),
        )

    def load(self, names: list[str]) -> ReferenceLoadResult:
        """Load bounded aggregated references in requested order without partial content.

        Args:
            names: One to thirty-two unique relative reference paths.

        Returns:
            Every requested aggregation when paths are safe, available, and within
            the response-size limit; otherwise an error-only result for this snapshot.
        """
        if not names:
            return self._error("empty_request", "At least one reference name is required.")
        if len(names) > _MAX_BATCH_REFERENCES:
            return self._error(
                "too_many_references",
                f"At most {_MAX_BATCH_REFERENCES} references may be loaded in one call.",
            )
        invalid = next((name for name in names if not _is_safe_name(name)), None)
        if invalid is not None:
            return self._error(
                "invalid_reference_name",
                "Reference names must be safe relative paths.",
                invalid,
            )
        duplicate = next((name for name in names if names.count(name) > 1), None)
        if duplicate is not None:
            return self._error(
                "duplicate_reference",
                "Reference names must be unique within one batch.",
                duplicate,
            )
        missing = next((name for name in names if name not in self._entries), None)
        if missing is not None:
            return self._error(
                "reference_not_found",
                "Every requested reference must exist in at least one configured scope.",
                missing,
            )
        content_bytes = sum(
            len(self._entries[name].content.encode("utf-8")) for name in names
        )
        if content_bytes > _MAX_BATCH_CONTENT_BYTES:
            return self._error(
                "content_limit_exceeded",
                f"Combined reference content exceeds {_MAX_BATCH_CONTENT_BYTES} bytes.",
            )
        return ReferenceLoadResult(
            ok=True,
            catalog_revision=self._revision,
            references=[self._entries[name].model_copy(deep=True) for name in names],
        )

    def _error(
        self,
        code: str,
        message: str,
        name: str | None = None,
    ) -> ReferenceLoadResult:
        return ReferenceLoadResult(
            ok=False,
            catalog_revision=self._revision,
            errors=[ReferenceLoadError(code=code, message=message, name=name)],
        )
