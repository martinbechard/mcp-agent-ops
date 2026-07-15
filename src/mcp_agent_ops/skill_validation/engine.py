#!/usr/bin/env python3
# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Validates Agent Skill source files and optional OpenAI adapter metadata.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml


MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
SKILL_FILE_NAME = "SKILL.md"
AGENTS_FOLDER_NAME = "agents"
OPENAI_METADATA_FILE_NAME = "openai.yaml"
FRONTMATTER_DELIMITER = "---"
ALLOWED_FRONTMATTER_KEYS = {
    "allowed-tools",
    "description",
    "license",
    "metadata",
    "name",
}
NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
SUCCESS_EXIT_CODE = 0
ERROR_EXIT_CODE = 1
OPENAI_METADATA_TOP_LEVEL_KEYS = {"dependencies", "interface", "policy"}
OPENAI_METADATA_INTERFACE_KEYS = {
    "brand_color",
    "default_prompt",
    "display_name",
    "icon_large",
    "icon_small",
    "short_description",
}
OPENAI_METADATA_POLICY_KEYS = {"allow_implicit_invocation"}


@dataclass(frozen=True)
class SkillFinding:
    """Describe one invalid skill file or adapter metadata condition."""

    path: Path
    message: str


def split_frontmatter(text: str) -> tuple[dict[str, object], bool]:
    """Parse leading YAML frontmatter and report whether it is a mapping."""
    lines = text.splitlines()
    if not lines or lines[0] != FRONTMATTER_DELIMITER:
        return {}, False

    for index, line in enumerate(lines[1:], start=1):
        if line == FRONTMATTER_DELIMITER:
            frontmatter_text = "\n".join(lines[1:index])
            try:
                parsed = yaml.safe_load(frontmatter_text)
            except yaml.YAMLError as error:
                return {"__yaml_error__": str(error)}, False
            return parsed if isinstance(parsed, dict) else {}, isinstance(parsed, dict)

    return {}, False


def skill_files_from_path(path: Path) -> list[Path]:
    """Expand a root, skill directory, or exact manifest into skill files."""
    if path.name == SKILL_FILE_NAME:
        return [path]
    if (path / SKILL_FILE_NAME).is_file():
        return [path / SKILL_FILE_NAME]
    if path.is_dir():
        return sorted(child / SKILL_FILE_NAME for child in path.iterdir() if (child / SKILL_FILE_NAME).is_file())
    return [path / SKILL_FILE_NAME]


def validate_skill_file(skill_file: Path) -> list[SkillFinding]:
    """Validate one Agent Skill manifest and its optional OpenAI metadata."""
    findings: list[SkillFinding] = []
    if not skill_file.is_file():
        return [SkillFinding(skill_file, "SKILL.md is missing")]

    frontmatter, parsed = split_frontmatter(skill_file.read_text(encoding="utf-8"))
    if "__yaml_error__" in frontmatter:
        return [SkillFinding(skill_file, f"frontmatter YAML is invalid: {frontmatter['__yaml_error__']}")]
    if not parsed:
        return [SkillFinding(skill_file, "SKILL.md must start with YAML frontmatter")]

    unexpected_keys = sorted(set(frontmatter) - ALLOWED_FRONTMATTER_KEYS)
    if unexpected_keys:
        findings.append(SkillFinding(skill_file, "unexpected frontmatter keys: " + ", ".join(unexpected_keys)))

    name = frontmatter.get("name")
    if not isinstance(name, str) or not name.strip():
        findings.append(SkillFinding(skill_file, "frontmatter name must be a non-empty string"))
    else:
        normalized_name = name.strip()
        if not NAME_PATTERN.fullmatch(normalized_name):
            findings.append(SkillFinding(skill_file, "frontmatter name must use lowercase letters, digits, and hyphens"))
        if normalized_name.startswith("-") or normalized_name.endswith("-") or "--" in normalized_name:
            findings.append(SkillFinding(skill_file, "frontmatter name must not start or end with a hyphen or contain repeated hyphens"))
        if len(normalized_name) > MAX_SKILL_NAME_LENGTH:
            findings.append(SkillFinding(skill_file, f"frontmatter name must be at most {MAX_SKILL_NAME_LENGTH} characters"))
        if skill_file.parent.name != normalized_name:
            findings.append(SkillFinding(skill_file, "frontmatter name must match the skill directory name"))

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        findings.append(SkillFinding(skill_file, "frontmatter description must be a non-empty string"))
    else:
        normalized_description = description.strip()
        if "<" in normalized_description or ">" in normalized_description:
            findings.append(SkillFinding(skill_file, "frontmatter description must not contain angle brackets"))
        if len(normalized_description) > MAX_DESCRIPTION_LENGTH:
            findings.append(SkillFinding(skill_file, f"frontmatter description must be at most {MAX_DESCRIPTION_LENGTH} characters"))

    findings.extend(validate_openai_metadata(skill_file.parent))

    return findings


def validate_openai_metadata(skill_directory: Path) -> list[SkillFinding]:
    """Validate optional `agents/openai.yaml` metadata for one skill directory."""
    metadata_path = skill_directory / AGENTS_FOLDER_NAME / OPENAI_METADATA_FILE_NAME
    if not metadata_path.exists():
        return []
    if not metadata_path.is_file():
        return [SkillFinding(metadata_path, "openai.yaml must be a file")]

    try:
        metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        return [SkillFinding(metadata_path, f"openai.yaml YAML is invalid: {error}")]

    if metadata is None:
        return [SkillFinding(metadata_path, "openai.yaml must not be empty")]
    if not isinstance(metadata, dict):
        return [SkillFinding(metadata_path, "openai.yaml must be a YAML object")]

    findings: list[SkillFinding] = []
    unexpected_keys = sorted(set(metadata) - OPENAI_METADATA_TOP_LEVEL_KEYS)
    if unexpected_keys:
        findings.append(SkillFinding(metadata_path, "unexpected openai.yaml top-level keys: " + ", ".join(unexpected_keys)))

    interface = metadata.get("interface")
    if interface is not None:
        if not isinstance(interface, dict):
            findings.append(SkillFinding(metadata_path, "interface must be a YAML object"))
        else:
            unexpected_interface_keys = sorted(set(interface) - OPENAI_METADATA_INTERFACE_KEYS)
            if unexpected_interface_keys:
                findings.append(SkillFinding(metadata_path, "unexpected interface keys: " + ", ".join(unexpected_interface_keys)))

    policy = metadata.get("policy")
    if policy is not None:
        if not isinstance(policy, dict):
            findings.append(SkillFinding(metadata_path, "policy must be a YAML object"))
        else:
            unexpected_policy_keys = sorted(set(policy) - OPENAI_METADATA_POLICY_KEYS)
            if unexpected_policy_keys:
                findings.append(SkillFinding(metadata_path, "unexpected policy keys: " + ", ".join(unexpected_policy_keys)))
            allow_implicit_invocation = policy.get("allow_implicit_invocation")
            if allow_implicit_invocation is not None and not isinstance(allow_implicit_invocation, bool):
                findings.append(SkillFinding(metadata_path, "policy allow_implicit_invocation must be a boolean"))

    dependencies = metadata.get("dependencies")
    if dependencies is not None and not isinstance(dependencies, dict):
        findings.append(SkillFinding(metadata_path, "dependencies must be a YAML object"))

    return findings


def validate_skill_paths(paths: list[Path]) -> list[SkillFinding]:
    """Validate every skill resolved from the requested roots and paths."""
    findings: list[SkillFinding] = []
    for path in paths:
        skill_files = skill_files_from_path(path)
        if not skill_files:
            findings.append(SkillFinding(path, "no skill files found"))
            continue
        for skill_file in skill_files:
            findings.extend(validate_skill_file(skill_file))
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run the copied validator CLI and return its stable success or error code."""
    parser = argparse.ArgumentParser(description="Validate Agent Skill source files")
    parser.add_argument("paths", nargs="+", help="Skill roots, skill directories, or SKILL.md files")
    args = parser.parse_args(argv)

    findings = validate_skill_paths([Path(path) for path in args.paths])
    if not findings:
        print("Agent skill validation passed.")
        return SUCCESS_EXIT_CODE

    for finding in findings:
        print(f"- {finding.path}: {finding.message}")
    return ERROR_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
