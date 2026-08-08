# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Loads allowlisted direct text files from every configured scope into immutable aggregations.
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
    return (
        bool(name)
        and name not in {".", ".."}
        and not name.startswith(".")
        and not {"/", "\\", "\0"} & set(name)
    )


def _within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _revision(allowed_names: list[str], entries: dict[str, AggregatedReference]) -> str:
    payload = {
        "allowed_names": allowed_names,
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
    """Own one immutable snapshot of allowlisted direct reference files.

    Use :meth:`from_scopes` with an authorized project root and administrator-configured
    reference roots. The resulting instance can service repeated model-facing loads while
    keeping content and digests paired until the caller builds a replacement snapshot.
    """

    def __init__(
        self,
        allowed_names: list[str],
        entries: dict[str, AggregatedReference],
    ) -> None:
        self._allowed_name_set = frozenset(allowed_names)
        self._entries = {
            name: entry.model_copy(deep=True) for name, entry in entries.items()
        }
        self._revision = _revision(list(allowed_names), self._entries)

    @classmethod
    def from_scopes(
        cls,
        project_root: Path | None,
        roots: list[Path],
        allowed_names: list[str],
    ) -> ReferenceCatalog:
        """Build a project-first snapshot from direct UTF-8 files in every scope.

        Args:
            project_root: Optional authorized working-project root searched first.
            roots: Administrator-configured reference roots searched in caller order.
            allowed_names: Complete direct filenames that model-facing callers may load.

        Returns:
            An immutable path-free catalog containing every available aggregation.

        Raises:
            OSError: If a matching reference cannot be read.
            UnicodeError: If a matching reference is not valid UTF-8 text.
            ValueError: If configuration is unsafe, a matching path escapes its scope,
                a matching path is not a regular file, or a name has too many sources.
        """
        if len(set(allowed_names)) != len(allowed_names):
            raise ValueError("Configured reference names must be unique.")
        if any(not _is_safe_name(name) for name in allowed_names):
            raise ValueError("Configured reference names must be a safe direct filename.")

        scopes: list[tuple[str, Path]] = []
        if project_root is not None:
            scopes.append(("project", project_root.expanduser().resolve()))
        scopes.extend(
            (f"configured:{index}", root.expanduser().resolve())
            for index, root in enumerate(roots)
        )

        entries: dict[str, AggregatedReference] = {}
        for name in allowed_names:
            contents: list[str] = []
            sources: list[ReferenceSourceMetadata] = []
            seen_paths: set[Path] = set()
            for scope, root in scopes:
                if not root.is_dir():
                    continue
                candidate = root / name
                resolved = candidate.resolve()
                if not _within_root(resolved, root):
                    raise ValueError(
                        f"Reference '{name}' resolves outside its configured scope."
                    )
                if not candidate.exists() and not candidate.is_symlink():
                    continue
                if not resolved.is_file():
                    raise ValueError(f"Reference '{name}' must be a regular file.")
                if resolved in seen_paths:
                    continue
                seen_paths.add(resolved)
                content_bytes = resolved.read_bytes()
                content = content_bytes.decode("utf-8")
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
            if sources:
                content = "\n".join(contents)
                entries[name] = AggregatedReference(
                    name=name,
                    digest=_digest(content.encode("utf-8")),
                    content=content,
                    source_count=len(sources),
                    sources=sources,
                )
        return cls(list(allowed_names), entries)

    def public_result(self) -> PublishedReferenceCatalog:
        """Return the current revision and available names without host paths."""
        return PublishedReferenceCatalog(
            revision=self._revision,
            names=sorted(self._entries),
        )

    def load(self, names: list[str]) -> ReferenceLoadResult:
        """Load bounded aggregated references in requested order without partial content.

        Args:
            names: One to thirty-two unique direct reference filenames.

        Returns:
            Every requested aggregation when names are safe, allowed, available, and within
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
                "Reference names must be safe direct filenames.",
                invalid,
            )
        duplicate = next((name for name in names if names.count(name) > 1), None)
        if duplicate is not None:
            return self._error(
                "duplicate_reference",
                "Reference names must be unique within one batch.",
                duplicate,
            )
        unallowed = next(
            (name for name in names if name not in self._allowed_name_set),
            None,
        )
        if unallowed is not None:
            return self._error(
                "reference_not_allowed",
                "Every requested reference must be explicitly configured.",
                unallowed,
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
