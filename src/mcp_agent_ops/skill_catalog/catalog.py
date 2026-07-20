# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Discovers precedence-ordered and selected recursive skill roots with safe content access.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from mcp_agent_ops.skill_catalog.models import (
    BatchLoadedSkill,
    LoadedSkill,
    LoadedSkillResource,
    PublishedSkillCatalog,
    PublishedSkillEntry,
    SkillCatalogResult,
    SkillEntry,
    SkillLoadError,
    SkillLoadResult,
    SkillResourceLoadError,
    SkillResourceLoadResult,
    SkillResourceRequest,
)

_MAX_BATCH_SKILLS = 32
_MAX_BATCH_CONTENT_BYTES = 1024 * 1024
_MAX_BATCH_RESOURCES = 64
_MAX_BATCH_RESOURCE_BYTES = 2 * 1024 * 1024


class SkillNotFoundError(KeyError):
    """Report that no configured root provides the requested skill name."""


class SkillResourceError(ValueError):
    """Report an unsafe, missing, or unreadable supporting skill resource."""


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _frontmatter(content: str, path: Path) -> dict[str, Any]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"SKILL.md must start with YAML frontmatter: {path}")
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as error:
        raise ValueError(f"SKILL.md YAML frontmatter is not closed: {path}") from error
    value = yaml.safe_load("\n".join(lines[1:closing]))
    if not isinstance(value, dict):
        raise ValueError(f"SKILL.md YAML frontmatter must be a mapping: {path}")
    return value


def _resources(skill_directory: Path) -> list[str]:
    resources: list[str] = []
    for candidate in skill_directory.rglob("*"):
        if (
            candidate.name == "SKILL.md"
            or not candidate.is_file()
            or any(
                part.startswith(".")
                for part in candidate.relative_to(skill_directory).parts
            )
        ):
            continue
        resolved = candidate.resolve()
        if resolved != skill_directory and skill_directory not in resolved.parents:
            continue
        resources.append(candidate.relative_to(skill_directory).as_posix())
    return sorted(resources)


def _within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _skill_files(root: Path, recursive: bool) -> list[Path]:
    exact = root / "SKILL.md"
    if exact.is_file():
        return [exact]
    candidates = root.rglob("SKILL.md") if recursive else root.glob("*/SKILL.md")
    return sorted(
        candidate
        for candidate in candidates
        if not any(
            part.startswith(".")
            for part in candidate.relative_to(root).parts[:-1]
        )
    )


def _catalog_revision(entries: dict[str, SkillEntry]) -> str:
    payload = [
        {
            "name": name,
            "digest": entry.digest,
            "resources": entry.resources,
        }
        for name, entry in sorted(entries.items())
    ]
    return _digest(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class SkillCatalog:
    """Index configured skill roots in caller-defined precedence order.

    Example:
        `SkillCatalog.from_roots([Path.home() / ".codex/skills"]).read_skill("python")`

    Instances hold an immutable manifest and resource-name snapshot. Create a new instance
    after installed skills change. Resource bytes are loaded progressively from disk, and
    reading methods never mutate skill roots.
    """

    def __init__(
        self,
        roots: list[Path],
        entries: dict[str, SkillEntry],
        contents: dict[str, str],
    ) -> None:
        self._roots = roots
        self._entries = entries
        self._contents = contents
        self._revision = _catalog_revision(entries)

    @classmethod
    def from_roots(
        cls,
        roots: list[Path],
        recursive_roots: Sequence[Path] | None = None,
    ) -> SkillCatalog:
        """Discover complete `SKILL.md` files from precedence-ordered roots.

        Args:
            roots: Exact skill directories or directories containing skill directories.
                Earlier roots win when multiple roots declare the same skill name.
            recursive_roots: Selected members of `roots` whose nested directories are
                recursively searched for skill manifests. Other roots retain one-level
                discovery for compatibility.

        Returns:
            A snapshot catalog including lower-precedence shadowed definition paths.

        Raises:
            ValueError: If a discovered skill has invalid or incomplete frontmatter, or
                one recursive root contains ambiguous definitions of the same skill name.
        """
        resolved_roots = [root.expanduser().resolve() for root in roots]
        resolved_recursive_roots = {
            root.expanduser().resolve() for root in recursive_roots or []
        }
        if not resolved_recursive_roots.issubset(resolved_roots):
            raise ValueError("Recursive skill roots must also be configured skill roots.")
        entries: dict[str, SkillEntry] = {}
        contents: dict[str, str] = {}
        for root in resolved_roots:
            if not root.is_dir():
                continue
            names_in_root: dict[str, Path] = {}
            for skill_file in _skill_files(root, root in resolved_recursive_roots):
                resolved_skill_file = skill_file.resolve()
                if not any(_within_root(resolved_skill_file, allowed) for allowed in resolved_roots):
                    raise ValueError(
                        f"SKILL.md resolves outside configured skill roots: {skill_file}"
                    )
                content_bytes = resolved_skill_file.read_bytes()
                content = content_bytes.decode("utf-8")
                metadata = _frontmatter(content, resolved_skill_file)
                name = metadata.get("name")
                description = metadata.get("description")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f"SKILL.md frontmatter name must be a non-empty string: {resolved_skill_file}")
                if not isinstance(description, str) or not description.strip():
                    raise ValueError(
                        f"SKILL.md frontmatter description must be a non-empty string: {resolved_skill_file}"
                    )
                if root in resolved_recursive_roots:
                    duplicate = names_in_root.get(name)
                    if duplicate is not None and duplicate != resolved_skill_file:
                        raise ValueError(
                            f"Recursive skill root contains duplicate skill name '{name}': {root}"
                        )
                    names_in_root[name] = resolved_skill_file
                existing = entries.get(name)
                if existing is not None:
                    if existing.path != str(resolved_skill_file):
                        existing.shadowed_paths.append(str(resolved_skill_file))
                    continue
                entries[name] = SkillEntry(
                    name=name,
                    description=description,
                    path=str(resolved_skill_file),
                    root=str(root),
                    digest=_digest(content_bytes),
                    resources=_resources(resolved_skill_file.parent),
                )
                contents[name] = content
        return cls(resolved_roots, entries, contents)

    def result(self) -> SkillCatalogResult:
        """Return roots and entries as a stable structured catalog result."""
        return SkillCatalogResult(
            revision=self._revision,
            roots=[str(root) for root in self._roots],
            skills=[self._entries[name].model_copy(deep=True) for name in sorted(self._entries)],
        )

    def public_result(self) -> PublishedSkillCatalog:
        """Return path-free catalog metadata safe for model-facing adapters."""
        return PublishedSkillCatalog(
            revision=self._revision,
            skills=[
                PublishedSkillEntry(
                    name=entry.name,
                    description=entry.description,
                    digest=entry.digest,
                    resources=list(entry.resources),
                    shadowed_count=len(entry.shadowed_paths),
                )
                for entry in (self._entries[name] for name in sorted(self._entries))
            ],
        )

    def get(self, name: str) -> SkillEntry:
        """Return metadata for one resolved skill name.

        Raises:
            SkillNotFoundError: If the skill is absent from every configured root.
        """
        try:
            return self._entries[name].model_copy(deep=True)
        except KeyError as error:
            raise SkillNotFoundError(name) from error

    def read_skill(self, name: str) -> LoadedSkill:
        """Return one complete selected `SKILL.md` document from this snapshot."""
        entry = self.get(name)
        return LoadedSkill(entry=entry, content=self._contents[name])

    def read_model_skill(self, name: str) -> BatchLoadedSkill:
        """Return one complete selected skill without host filesystem paths."""
        entry = self.get(name)
        return BatchLoadedSkill(
            name=name,
            digest=entry.digest,
            content=self._contents[name],
            resources=list(entry.resources),
        )

    def load_skills(self, names: list[str]) -> SkillLoadResult:
        """Load a bounded ordered set of complete skills without returning partial content.

        Args:
            names: One to thirty-two unique resolved skill names in caller-required order.

        Returns:
            Complete model-facing documents when every name is valid and the response stays
            within the configured size limit; otherwise an error-only result.
        """
        if not names:
            return self._load_error("empty_request", "At least one skill name is required.")
        if len(names) > _MAX_BATCH_SKILLS:
            return self._load_error(
                "too_many_skills",
                f"At most {_MAX_BATCH_SKILLS} skills may be loaded in one call.",
            )
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            return self._load_error(
                "duplicate_skill",
                "Skill names must be unique within one batch.",
                duplicates[0],
            )
        missing = [name for name in names if name not in self._entries]
        if missing:
            return self._load_error(
                "skill_not_found",
                "Every requested skill must exist in the configured catalog.",
                missing[0],
            )
        content_bytes = sum(len(self._contents[name].encode("utf-8")) for name in names)
        if content_bytes > _MAX_BATCH_CONTENT_BYTES:
            return self._load_error(
                "content_limit_exceeded",
                f"Combined skill content exceeds {_MAX_BATCH_CONTENT_BYTES} bytes.",
            )
        return SkillLoadResult(
            ok=True,
            catalog_revision=self._revision,
            skills=[
                self.read_model_skill(name)
                for name in names
            ],
        )

    def _load_error(self, code: str, message: str, name: str | None = None) -> SkillLoadResult:
        return SkillLoadResult(
            ok=False,
            catalog_revision=self._revision,
            errors=[SkillLoadError(code=code, message=message, name=name)],
        )

    def load_resources(
        self,
        requests: list[SkillResourceRequest],
    ) -> SkillResourceLoadResult:
        """Load bounded supporting resources without returning a partial result.

        Args:
            requests: One to sixty-four unique skill-name and relative-resource pairs.

        Returns:
            Ordered resources when every request is safe and available; otherwise an
            error-only result tied to the current catalog revision.
        """
        if not requests:
            return self._resource_error(
                "empty_request",
                "At least one skill resource request is required.",
            )
        if len(requests) > _MAX_BATCH_RESOURCES:
            return self._resource_error(
                "too_many_resources",
                f"At most {_MAX_BATCH_RESOURCES} resources may be loaded in one call.",
            )
        identities = [
            (request.skill_name, request.resource_path) for request in requests
        ]
        duplicates = sorted({identity for identity in identities if identities.count(identity) > 1})
        if duplicates:
            skill_name, resource_path = duplicates[0]
            return self._resource_error(
                "duplicate_resource",
                "Skill resource requests must be unique within one batch.",
                skill_name,
                resource_path,
            )
        loaded: list[LoadedSkillResource] = []
        for request in requests:
            try:
                loaded.append(
                    self.read_resource(request.skill_name, request.resource_path)
                )
            except (SkillNotFoundError, SkillResourceError, OSError, UnicodeError) as error:
                return self._resource_error(
                    "resource_unavailable",
                    str(error),
                    request.skill_name,
                    request.resource_path,
                )
        encoded_size = sum(
            len(resource.content.encode("utf-8"))
            if resource.content is not None
            else len(resource.data_base64 or "")
            for resource in loaded
        )
        if encoded_size > _MAX_BATCH_RESOURCE_BYTES:
            return self._resource_error(
                "content_limit_exceeded",
                f"Combined resource content exceeds {_MAX_BATCH_RESOURCE_BYTES} bytes.",
            )
        return SkillResourceLoadResult(
            ok=True,
            catalog_revision=self._revision,
            resources=loaded,
        )

    def _resource_error(
        self,
        code: str,
        message: str,
        skill_name: str | None = None,
        resource_path: str | None = None,
    ) -> SkillResourceLoadResult:
        return SkillResourceLoadResult(
            ok=False,
            catalog_revision=self._revision,
            errors=[
                SkillResourceLoadError(
                    code=code,
                    message=message,
                    skill_name=skill_name,
                    resource_path=resource_path,
                )
            ],
        )

    def read_resource(self, name: str, resource_path: str) -> LoadedSkillResource:
        """Read one supporting resource without permitting skill-directory escape.

        Args:
            name: Resolved skill name.
            resource_path: Path relative to the directory containing the selected `SKILL.md`.

        Returns:
            UTF-8 resources as text and other resources as base64, with MIME type and digest.

        Raises:
            SkillNotFoundError: If `name` is absent.
            SkillResourceError: If the resource is absolute, absent from the active snapshot,
                escapes through traversal or a symlink, is missing, or names a directory.
        """
        entry = self.get(name)
        skill_directory = Path(entry.path).parent.resolve()
        requested = Path(resource_path)
        if requested.is_absolute():
            raise SkillResourceError(f"Skill resource path must be relative: {resource_path}")
        candidate = (skill_directory / requested).resolve()
        if candidate == skill_directory or skill_directory not in candidate.parents:
            raise SkillResourceError(f"Resource is outside the skill directory: {resource_path}")
        relative = candidate.relative_to(skill_directory).as_posix()
        if relative not in entry.resources:
            raise SkillResourceError(
                f"Skill resource is not published in the catalog snapshot: {resource_path}"
            )
        if not candidate.is_file():
            raise SkillResourceError(f"Skill resource does not exist: {resource_path}")
        content = candidate.read_bytes()
        mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            return LoadedSkillResource(
                skill_name=name,
                path=relative,
                mime_type=mime_type,
                digest=_digest(content),
                data_base64=base64.b64encode(content).decode("ascii"),
            )
        return LoadedSkillResource(
            skill_name=name,
            path=relative,
            mime_type=mime_type,
            digest=_digest(content),
            content=text,
        )
