# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Discovers precedence-ordered skills and safely returns complete skill content and resources.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import base64
import hashlib
import mimetypes
from pathlib import Path
from typing import Any

import yaml

from mcp_agent_ops.skill_catalog.models import LoadedSkill, LoadedSkillResource, SkillCatalogResult, SkillEntry


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
            or any(part.startswith(".") for part in candidate.parts)
        ):
            continue
        resolved = candidate.resolve()
        if resolved != skill_directory and skill_directory not in resolved.parents:
            continue
        resources.append(candidate.relative_to(skill_directory).as_posix())
    return sorted(resources)


class SkillCatalog:
    """Index configured skill roots in caller-defined precedence order.

    Example:
        `SkillCatalog.from_roots([Path.home() / ".codex/skills"]).read_skill("python")`

    Instances hold an immutable discovery snapshot. Create a new instance after installed
    skills change. Reading methods perform filesystem I/O but never mutate skill roots.
    """

    def __init__(self, roots: list[Path], entries: dict[str, SkillEntry]) -> None:
        self._roots = roots
        self._entries = entries

    @classmethod
    def from_roots(cls, roots: list[Path]) -> SkillCatalog:
        """Discover complete `SKILL.md` files from precedence-ordered roots.

        Args:
            roots: Directories whose immediate children may be skill directories. Earlier
                roots win when multiple definitions declare the same skill name.

        Returns:
            A snapshot catalog including lower-precedence shadowed definition paths.

        Raises:
            ValueError: If a discovered skill has invalid or incomplete frontmatter.
        """
        resolved_roots = [root.expanduser().resolve() for root in roots]
        entries: dict[str, SkillEntry] = {}
        for root in resolved_roots:
            if not root.is_dir():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                content_bytes = skill_file.read_bytes()
                content = content_bytes.decode("utf-8")
                metadata = _frontmatter(content, skill_file)
                name = metadata.get("name")
                description = metadata.get("description")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f"SKILL.md frontmatter name must be a non-empty string: {skill_file}")
                if not isinstance(description, str) or not description.strip():
                    raise ValueError(f"SKILL.md frontmatter description must be a non-empty string: {skill_file}")
                existing = entries.get(name)
                if existing is not None:
                    existing.shadowed_paths.append(str(skill_file.resolve()))
                    continue
                entries[name] = SkillEntry(
                    name=name,
                    description=description,
                    path=str(skill_file.resolve()),
                    root=str(root),
                    digest=_digest(content_bytes),
                    resources=_resources(skill_file.parent.resolve()),
                )
        return cls(resolved_roots, entries)

    def result(self) -> SkillCatalogResult:
        """Return roots and entries as a stable structured catalog result."""
        return SkillCatalogResult(
            roots=[str(root) for root in self._roots],
            skills=[self._entries[name] for name in sorted(self._entries)],
        )

    def get(self, name: str) -> SkillEntry:
        """Return metadata for one resolved skill name.

        Raises:
            SkillNotFoundError: If the skill is absent from every configured root.
        """
        try:
            return self._entries[name]
        except KeyError as error:
            raise SkillNotFoundError(name) from error

    def read_skill(self, name: str) -> LoadedSkill:
        """Read and return one complete selected `SKILL.md` document."""
        entry = self.get(name)
        return LoadedSkill(entry=entry, content=Path(entry.path).read_text(encoding="utf-8"))

    def read_resource(self, name: str, resource_path: str) -> LoadedSkillResource:
        """Read one supporting resource without permitting skill-directory escape.

        Args:
            name: Resolved skill name.
            resource_path: Path relative to the directory containing the selected `SKILL.md`.

        Returns:
            UTF-8 resources as text and other resources as base64, with MIME type and digest.

        Raises:
            SkillNotFoundError: If `name` is absent.
            SkillResourceError: If the resource is absolute, escapes through traversal or a
                symlink, is missing, or names a directory.
        """
        entry = self.get(name)
        skill_directory = Path(entry.path).parent.resolve()
        requested = Path(resource_path)
        candidate = requested.resolve() if requested.is_absolute() else (skill_directory / requested).resolve()
        if candidate == skill_directory or skill_directory not in candidate.parents:
            raise SkillResourceError(f"Resource is outside the skill directory: {resource_path}")
        if not candidate.is_file():
            raise SkillResourceError(f"Skill resource does not exist: {resource_path}")
        content = candidate.read_bytes()
        relative = candidate.relative_to(skill_directory).as_posix()
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
