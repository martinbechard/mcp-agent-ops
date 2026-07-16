#!/usr/bin/env python3
# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Modified with AI assistance.
# Summary: Detects setup-time technology skills from explicit repository evidence clauses.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import re
import sys
import tomllib
from pathlib import Path

import yaml


HERE = Path(__file__).resolve()
if HERE.parent.name == "scripts" and HERE.parents[1].name == "detect-technology-skills":
    DEFAULT_SKILLS_ROOT = HERE.parents[2]
    DEFAULT_REGISTRY = HERE.parents[1] / "references" / "technology-skill-detection-registry.yaml"
else:
    REPOSITORY_ROOT = HERE.parents[1]
    DEFAULT_SKILLS_ROOT = REPOSITORY_ROOT / "skills"
    DEFAULT_REGISTRY = DEFAULT_SKILLS_ROOT / "detect-technology-skills" / "references" / "technology-skill-detection-registry.yaml"

IGNORED_PARTS = {".git", ".next", ".venv", "__pycache__", "dist", "node_modules", "target", "venv"}
OWNER_FILE_NAMES = {"package.json", "pom.xml", "pyproject.toml"}
OWNER_FILE_GLOBS = ("build.gradle*", "requirements*.txt")


def load_yaml(path: Path) -> dict[str, object]:
    """Load one YAML mapping so malformed registry inputs fail at the command boundary."""
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping: {path}")
    return value


def _within_project(path: Path, root: Path) -> bool:
    """Return whether a path remains inside the project after symlink resolution."""
    try:
        resolved = path.resolve()
        resolved_root = root.resolve()
    except OSError:
        return False
    return resolved == resolved_root or resolved_root in resolved.parents


def _project_path_label(path: Path, root: Path) -> str:
    """Return a lexical project-relative diagnostic label without exposing host paths."""
    try:
        return path.expanduser().absolute().relative_to(root.expanduser().absolute()).as_posix()
    except ValueError:
        return path.name


def relative(path: Path, root: Path) -> str:
    """Return a stable project-relative evidence path without disclosing external paths."""
    if not _within_project(path, root):
        return "[outside-project]"
    return _project_path_label(path, root)


def _read_project_text(path: Path, root: Path) -> str:
    """Read one project file only after canonical containment is rechecked."""
    resolved = path.resolve()
    if not _within_project(resolved, root):
        raise OSError("project file resolves outside the project root")
    return resolved.read_text(encoding="utf-8")


def is_ignored(path: Path, root: Path) -> bool:
    """Report whether a path belongs to a generated, dependency, or environment directory."""
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return bool(set(parts) & IGNORED_PARTS)


def scope_files(root: Path, scope: Path) -> tuple[list[Path], list[str]]:
    """List contained human-relevant files and path-escape diagnostics for one scope."""
    path = scope if scope.is_absolute() else root / scope
    if path.is_file():
        if _within_project(path, root):
            return [path], []
        return [], [_project_path_label(path, root)]
    if not path.is_dir():
        return [], []
    files: list[Path] = []
    unsafe: list[str] = []
    for child in path.rglob("*"):
        if child.is_symlink() and not _within_project(child, root):
            unsafe.append(_project_path_label(child, root))
            continue
        if child.is_file() and _within_project(child, root) and not is_ignored(child, root):
            files.append(child)
    return sorted(files), sorted(set(unsafe))


def owner_files(directory: Path, root: Path) -> tuple[list[Path], list[str]]:
    """Find contained project manifests and report manifest symlink escapes."""
    candidates = [directory / name for name in OWNER_FILE_NAMES]
    for pattern in OWNER_FILE_GLOBS:
        candidates.extend(directory.glob(pattern))
    found: list[Path] = []
    unsafe: list[str] = []
    for path in sorted(set(candidates)):
        if not _within_project(path, root):
            unsafe.append(_project_path_label(path, root))
        elif path.is_file():
            found.append(path)
    return found, sorted(set(unsafe))


def nearest_owner_files(
    root: Path,
    scope: Path,
    files: list[Path],
) -> tuple[list[Path], list[str]]:
    """Find nearest contained owner manifests and report any manifest root escape."""
    candidates = files or [scope if scope.is_absolute() else root / scope]
    owners: set[Path] = set()
    unsafe: set[str] = set()
    for candidate in candidates:
        current = candidate.parent if candidate.is_file() else candidate
        if not current.exists():
            current = current.parent
        while current == root or root in current.parents:
            matches, escaped = owner_files(current, root)
            unsafe.update(escaped)
            if escaped:
                break
            if matches:
                owners.update(matches)
                break
            if current == root:
                break
            current = current.parent
    return sorted(owners), sorted(unsafe)


def manifest_dependencies(paths: list[Path], root: Path | None = None) -> set[str]:
    """Extract normalized dependency names from contained owning manifests."""
    dependencies: set[str] = set()
    for path in paths:
        try:
            text = _read_project_text(path, root) if root is not None else path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.name == "package.json":
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                continue
            for field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                if isinstance(value.get(field), dict):
                    dependencies.update(str(name) for name in value[field])
        elif path.name == "pyproject.toml":
            try:
                value = tomllib.loads(text)
            except tomllib.TOMLDecodeError:
                continue
            project = value.get("project", {})
            for item in project.get("dependencies", []) if isinstance(project, dict) else []:
                if isinstance(item, str):
                    dependencies.add(re.split(r"[<>=!~;\s\[]", item, maxsplit=1)[0].lower())
            optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
            if isinstance(optional, dict):
                for items in optional.values():
                    for item in items if isinstance(items, list) else []:
                        if isinstance(item, str):
                            dependencies.add(re.split(r"[<>=!~;\s\[]", item, maxsplit=1)[0].lower())
            poetry = value.get("tool", {}).get("poetry", {}).get("dependencies", {})
            if isinstance(poetry, dict):
                dependencies.update(str(name).lower() for name in poetry if str(name).lower() != "python")
        elif fnmatch.fnmatch(path.name, "requirements*.txt"):
            for line in text.splitlines():
                item = line.strip()
                if item and not item.startswith(("#", "-")):
                    dependencies.add(re.split(r"[<>=!~;\s\[]", item, maxsplit=1)[0].lower())
    return dependencies


def glob_matches(value: str, pattern: str) -> bool:
    """Match a project path with globstar segments that may span zero or more directories."""
    expression = ""
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    expression += "(?:.*/)?"
                    index += 1
                else:
                    expression += ".*"
                continue
            expression += "[^/]*"
        elif character == "?":
            expression += "[^/]"
        elif character == "[":
            closing = pattern.find("]", index + 1)
            if closing == -1:
                expression += re.escape(character)
            else:
                values = pattern[index + 1:closing]
                if values.startswith("!"):
                    values = "^" + values[1:]
                expression += "[" + values.replace("\\", "\\\\") + "]"
                index = closing
        else:
            expression += re.escape(character)
        index += 1
    return re.fullmatch(expression, value) is not None


def python_imports_module(path: Path, module: str, root: Path | None = None) -> bool:
    """Report whether contained parsed Python code imports a module."""
    try:
        text = _read_project_text(path, root) if root is not None else path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return False
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        if any(name == module or name.startswith(module + ".") for name in names):
            return True
    return False


def predicate_evidence(
    predicate: dict[str, object],
    root: Path,
    files: list[Path],
    owner_evidence: list[Path],
    dependencies: set[str],
) -> list[str]:
    """Evaluate one atomic evidence predicate and return its concrete match, if any."""
    key, expected = next(iter(predicate.items()))
    if key == "fileExtension":
        extension = str(expected).lower()
        match = next((path for path in files if path.suffix.lower() == extension), None)
        return [f"scope extension {extension}: {relative(match, root)}"] if match else []
    if key == "fileGlob":
        pattern = str(expected)
        match = next((path for path in files if glob_matches(relative(path, root), pattern)), None)
        return [f"scope path {pattern}: {relative(match, root)}"] if match else []
    if key == "fileMatch":
        pattern = str(expected["glob"])
        extensions = {str(value).lower() for value in expected["extensions"]}
        match = next(
            (
                path for path in files
                if path.suffix.lower() in extensions and glob_matches(relative(path, root), pattern)
            ),
            None,
        )
        return [f"scope code path {pattern}: {relative(match, root)}"] if match else []
    if key == "manifestFile":
        pattern = str(expected)
        match = next(
            (
                path for path in owner_evidence
                if glob_matches(relative(path, root), pattern) or glob_matches(path.name, pattern)
            ),
            None,
        )
        return [f"owning manifest {pattern}: {relative(match, root)}"] if match else []
    if key == "owningDependency":
        dependency = str(expected).lower()
        return [f"owning manifest dependency {expected}"] if dependency in dependencies else []
    if key in {"contentPattern", "owningContentPattern"}:
        pattern = str(expected["glob"])
        candidates = owner_evidence if key == "owningContentPattern" else sorted(set(files + owner_evidence))
        for path in candidates:
            if not glob_matches(relative(path, root), pattern) and not glob_matches(path.name, pattern):
                continue
            try:
                text = _read_project_text(path, root)
            except (OSError, UnicodeDecodeError):
                continue
            if str(expected["contains"]) in text:
                prefix = "owning content" if key == "owningContentPattern" else "content"
                return [f"{prefix} {expected['contains']}: {relative(path, root)}"]
        return []
    if key == "sourceImport":
        module = str(expected["module"])
        extensions = {str(value).lower() for value in expected["extensions"]}
        match = next(
            (
                path for path in files
                if path.suffix.lower() in extensions and python_imports_module(path, module, root)
            ),
            None,
        )
        return [f"source import {module}: {relative(match, root)}"] if match else []
    raise ValueError(f"Unknown activation predicate: {key}")


def clause_evidence(
    clause: dict[str, object],
    root: Path,
    files: list[Path],
    owner_evidence: list[Path],
    dependencies: set[str],
) -> list[str]:
    """Evaluate a nested any-of or all-of clause and retain evidence from satisfied branches."""
    if "anyOf" in clause:
        evidence = [
            item
            for child in clause["anyOf"]
            for item in clause_evidence(child, root, files, owner_evidence, dependencies)
        ]
        return list(dict.fromkeys(evidence))
    if "allOf" in clause:
        evidence: list[str] = []
        for child in clause["allOf"]:
            child_evidence = clause_evidence(child, root, files, owner_evidence, dependencies)
            if not child_evidence:
                return []
            evidence.extend(child_evidence)
        return list(dict.fromkeys(evidence))
    return predicate_evidence(clause, root, files, owner_evidence, dependencies)


def activation_evidence(
    entry: dict[str, object],
    root: Path,
    files: list[Path],
    owner_evidence: list[Path],
    dependencies: set[str],
) -> list[str]:
    """Return evidence when at least one complete activation branch selects the skill."""
    activation = entry.get("activation", {})
    return clause_evidence(activation, root, files, owner_evidence, dependencies)


def detect_scope(
    root: Path,
    scope: Path,
    registry: dict[str, object],
    skills_root: Path,
    available_skills: set[str] | None = None,
) -> dict[str, object]:
    """Detect and validate one requested project scope, returning a durable folder skillset."""
    target = (scope if scope.is_absolute() else root / scope).resolve()
    try:
        scope_value = target.relative_to(root).as_posix()
    except ValueError:
        scope_value = target.as_posix()
        return {
            "scope": scope_value,
            "pathPattern": scope_value,
            "skills": [],
            "sourceEvidence": [],
            "missingRequiredSkills": [],
            "exclusiveConflicts": [],
            "scopeErrors": ["scope resolves outside the project root"],
            "status": "BLOCKED",
        }
    if not target.exists():
        return {
            "scope": scope_value,
            "pathPattern": scope_value,
            "skills": [],
            "sourceEvidence": [],
            "missingRequiredSkills": [],
            "exclusiveConflicts": [],
            "scopeErrors": ["scope does not exist"],
            "status": "BLOCKED",
        }
    files, unsafe_scope_paths = scope_files(root, scope)
    if unsafe_scope_paths:
        return {
            "scope": scope_value,
            "pathPattern": scope_value + ("/**" if target.is_dir() else ""),
            "skills": [],
            "sourceEvidence": [],
            "missingRequiredSkills": [],
            "exclusiveConflicts": [],
            "scopeErrors": [
                "scope contains a path resolving outside the project root: "
                + ", ".join(unsafe_scope_paths)
            ],
            "status": "BLOCKED",
        }
    manifests, unsafe_manifests = nearest_owner_files(root, scope, files)
    if unsafe_manifests:
        return {
            "scope": scope_value,
            "pathPattern": scope_value + ("/**" if target.is_dir() else ""),
            "skills": [],
            "sourceEvidence": [],
            "missingRequiredSkills": [],
            "exclusiveConflicts": [],
            "scopeErrors": [
                "owning manifest resolves outside the project root: "
                + ", ".join(unsafe_manifests)
            ],
            "status": "BLOCKED",
        }
    owner_directories = sorted({path.parent for path in manifests})
    if len(owner_directories) > 1:
        return {
            "scope": scope_value,
            "pathPattern": scope_value + ("/**" if target.is_dir() else ""),
            "skills": [],
            "sourceEvidence": [],
            "missingRequiredSkills": [],
            "exclusiveConflicts": [],
            "scopeErrors": [
                "scope spans multiple owning manifest directories; analyze each owner separately: "
                + ", ".join(relative(path, root) for path in owner_directories)
            ],
            "status": "BLOCKED",
        }
    entries = {str(item["skill"]): item for item in registry.get("skills", [])}
    owner_evidence = set(manifests)
    unsafe_owner_evidence: set[str] = set()
    for path in manifests:
        for child in path.parent.iterdir():
            if child.is_symlink() and not _within_project(child, root):
                unsafe_owner_evidence.add(_project_path_label(child, root))
            elif child.is_file() and _within_project(child, root):
                owner_evidence.add(child)
    if unsafe_owner_evidence:
        return {
            "scope": scope_value,
            "pathPattern": scope_value + ("/**" if target.is_dir() else ""),
            "skills": [],
            "sourceEvidence": [],
            "missingRequiredSkills": [],
            "exclusiveConflicts": [],
            "scopeErrors": [
                "owning evidence resolves outside the project root: "
                + ", ".join(sorted(unsafe_owner_evidence))
            ],
            "status": "BLOCKED",
        }
    dependencies = manifest_dependencies(manifests, root)
    selected: dict[str, dict[str, object]] = {}
    missing: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    for skill, entry in entries.items():
        evidence = activation_evidence(
            entry,
            root,
            files,
            sorted(owner_evidence),
            dependencies,
        )
        if evidence:
            selected[skill] = {
                "entry": entry,
                "evidence": evidence,
                "source": "scope-evidence",
                "required": bool(entry.get("requiredWhenDetected", True)),
            }
    pending = list(selected)
    while pending:
        owner = pending.pop()
        for companion in selected[owner]["entry"].get("companions", []):
            if companion in selected:
                continue
            companion_entry = entries.get(str(companion))
            if companion_entry is None:
                missing.append({"skill": companion, "reason": f"required companion of {owner}"})
                continue
            selected[str(companion)] = {
                "entry": companion_entry,
                "evidence": [f"companion of {owner}"],
                "source": "companion",
                "required": True,
            }
            pending.append(str(companion))
    groups: dict[str, list[str]] = {}
    for skill, value in selected.items():
        entry = value["entry"]
        if entry.get("selection") == "exclusive":
            groups.setdefault(str(entry["exclusiveGroup"]), []).append(skill)
    for group, members in groups.items():
        if len(members) < 2:
            continue
        highest = min(int(selected[member]["entry"]["priority"]) for member in members)
        winners = [member for member in members if int(selected[member]["entry"]["priority"]) == highest]
        if len(winners) != 1:
            conflicts.append({"group": group, "skills": sorted(members), "reason": "equal-priority exclusive matches"})
        else:
            for member in members:
                if member != winners[0]:
                    selected.pop(member)
    evidence_rows: list[dict[str, object]] = []
    skills: list[str] = []
    for skill, value in sorted(selected.items(), key=lambda item: (int(item[1]["entry"]["priority"]), item[0])):
        skill_file = skills_root / skill / "SKILL.md"
        is_available = skill in available_skills if available_skills is not None else skill_file.is_file()
        if value["required"] and not is_available:
            missing.append({"skill": skill, "reason": "detected required skill is unavailable"})
        skills.append(skill)
        evidence_rows.append({
            "skill": skill,
            "source": value["source"],
            "evidence": value["evidence"],
            "runtimeAvailability": "AVAILABLE" if is_available else "UNAVAILABLE",
        })
    status = "BLOCKED" if missing or conflicts else "NO_VARIANT" if not skills else "READY"
    pattern = scope_value if any(char in scope_value for char in "*?[") else scope_value.rstrip("/") + ("/**" if target.is_dir() else "")
    return {
        "scope": scope_value,
        "pathPattern": pattern,
        "skills": skills,
        "sourceEvidence": evidence_rows,
        "missingRequiredSkills": missing,
        "exclusiveConflicts": conflicts,
        "scopeErrors": [],
        "status": status,
    }


def detect(args: argparse.Namespace) -> tuple[dict[str, object], int]:
    """Run detection for all requested scopes and return the aggregate process exit status."""
    root = args.project_root.resolve()
    configured_registry = getattr(args, "registry_data", None)
    registry = (
        configured_registry
        if isinstance(configured_registry, dict)
        else load_yaml(args.registry)
    )
    available_skills = set(args.available_skill) if args.available_skill is not None else None
    loadouts = [
        detect_scope(root, Path(value), registry, args.skills_root, available_skills)
        for value in args.scope
    ]
    blocked = any(item["status"] == "BLOCKED" for item in loadouts)
    result = {
        "schema": "dev-methodology-technology-skill-detection-result",
        "version": 1,
        "projectRoot": str(root),
        "runtimeSkillCatalog": {
            "source": "explicit --available-skill values" if available_skills is not None else "skills root",
            "skillsRoot": str(args.skills_root.resolve()),
            "availableSkills": sorted(available_skills) if available_skills is not None else None,
        },
        "loadouts": loadouts,
        "status": "BLOCKED" if blocked else "READY",
    }
    return result, 2 if blocked else 0


def main() -> int:
    """Parse command-line inputs, run detection, and print JSON or YAML output."""
    parser = argparse.ArgumentParser(description="Detect setup-time technology skills for selected project folders.")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--scope", action="append", required=True)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--skills-root", type=Path, default=DEFAULT_SKILLS_ROOT)
    parser.add_argument(
        "--available-skill",
        action="append",
        help="Skill id exposed by the target runtime; repeat to provide the complete runtime catalog.",
    )
    parser.add_argument("--format", choices=("json", "yaml"), default="json")
    args = parser.parse_args()
    try:
        result, exit_code = detect(args)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(error, file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True) if args.format == "json" else yaml.safe_dump(result, sort_keys=False), end="\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
