# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies copied technology-skill detection through its framework-independent service.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path
from unittest import mock

import yaml

from mcp_agent_ops.technology_detection import engine
from mcp_agent_ops.technology_detection.service import detect_technology_skills


def test_detection_requires_complete_activation_evidence(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skills = tmp_path / "skills"
    project.mkdir()
    (project / "main.py").write_text("from fastapi import FastAPI\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname = "example"\nversion = "1"\ndependencies = ["fastapi"]\n',
        encoding="utf-8",
    )
    skill = skills / "fastapi"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: fastapi\ndescription: FastAPI.\n---\n", encoding="utf-8")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "skills": [
                    {
                        "skill": "fastapi",
                        "activation": {
                            "allOf": [
                                {"owningDependency": "fastapi"},
                                {"sourceImport": {"module": "fastapi", "extensions": [".py"]}},
                            ]
                        },
                        "companions": [],
                        "selection": "additive",
                        "priority": 100,
                        "requiredWhenDetected": True,
                    },
                    {
                        "skill": "unmatched",
                        "activation": {"owningDependency": "not-installed"},
                        "companions": [],
                        "selection": "additive",
                        "priority": 200,
                        "requiredWhenDetected": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    with mock.patch.object(
        engine,
        "manifest_dependencies",
        wraps=engine.manifest_dependencies,
    ) as dependencies:
        result = detect_technology_skills(
            project,
            ["main.py"],
            registry,
            skills,
            ["fastapi"],
        )

    assert result.exit_code == 0
    assert dependencies.call_count == 1
    assert result.result["loadouts"][0]["skills"] == ["fastapi"]
    assert result.result["loadouts"][0]["status"] == "READY"


def test_detection_blocks_scopes_outside_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skills = tmp_path / "skills"
    project.mkdir()
    skills.mkdir()
    registry = tmp_path / "registry.yaml"
    registry.write_text("skills: []\n", encoding="utf-8")

    result = detect_technology_skills(project, ["../outside"], registry, skills, [])

    assert result.exit_code == 2
    assert result.result["loadouts"][0]["status"] == "BLOCKED"
    assert result.result["loadouts"][0]["scopeErrors"] == ["scope resolves outside the project root"]


def test_detection_blocks_nested_source_symlinks_outside_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "external.py"
    external.write_text("from fastapi import FastAPI\nSECRET_MARKER = True\n", encoding="utf-8")
    (project / "linked.py").symlink_to(external)
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump({
            "skills": [
                {
                    "skill": "fastapi",
                    "activation": {
                        "sourceImport": {"module": "fastapi", "extensions": [".py"]}
                    },
                    "companions": [],
                    "selection": "additive",
                    "priority": 100,
                    "requiredWhenDetected": True,
                },
                {
                    "skill": "secret-content",
                    "activation": {
                        "contentPattern": {"glob": "**/*.py", "contains": "SECRET_MARKER"}
                    },
                    "companions": [],
                    "selection": "additive",
                    "priority": 200,
                    "requiredWhenDetected": True,
                },
            ]
        }),
        encoding="utf-8",
    )

    result = detect_technology_skills(project, ["."], registry, tmp_path / "skills", [])

    loadout = result.result["loadouts"][0]
    assert result.exit_code == 2
    assert loadout["status"] == "BLOCKED"
    assert loadout["skills"] == []
    assert loadout["scopeErrors"] == [
        "scope contains a path resolving outside the project root: linked.py"
    ]
    assert str(external) not in str(result.result)


def test_detection_blocks_external_owner_manifest_symlink(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print('safe')\n", encoding="utf-8")
    external_manifest = tmp_path / "pyproject.toml"
    external_manifest.write_text(
        '[project]\nname = "external"\nversion = "1"\ndependencies = ["fastapi"]\n',
        encoding="utf-8",
    )
    (project / "pyproject.toml").symlink_to(external_manifest)
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump({
            "skills": [{
                "skill": "fastapi",
                "activation": {"owningDependency": "fastapi"},
                "companions": [],
                "selection": "additive",
                "priority": 100,
                "requiredWhenDetected": True,
            }]
        }),
        encoding="utf-8",
    )

    result = detect_technology_skills(project, ["main.py"], registry, tmp_path / "skills", [])

    loadout = result.result["loadouts"][0]
    assert result.exit_code == 2
    assert loadout["status"] == "BLOCKED"
    assert loadout["skills"] == []
    assert loadout["scopeErrors"] == [
        "owning manifest resolves outside the project root: pyproject.toml"
    ]
    assert str(external_manifest) not in str(result.result)


def test_detection_blocks_external_owner_evidence_symlink(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "main.py").write_text("print('safe')\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        '[project]\nname = "safe"\nversion = "1"\n',
        encoding="utf-8",
    )
    external_marker = tmp_path / "marker.yaml"
    external_marker.write_text("framework: secret\n", encoding="utf-8")
    (project / "marker.yaml").symlink_to(external_marker)
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump({
            "skills": [{
                "skill": "secret-framework",
                "activation": {
                    "owningContentPattern": {
                        "glob": "marker.yaml",
                        "contains": "framework: secret",
                    }
                },
                "companions": [],
                "selection": "additive",
                "priority": 100,
                "requiredWhenDetected": True,
            }]
        }),
        encoding="utf-8",
    )

    result = detect_technology_skills(project, ["main.py"], registry, tmp_path / "skills", [])

    loadout = result.result["loadouts"][0]
    assert result.exit_code == 2
    assert loadout["status"] == "BLOCKED"
    assert loadout["skills"] == []
    assert loadout["scopeErrors"] == [
        "owning evidence resolves outside the project root: marker.yaml"
    ]
    assert str(external_marker) not in str(result.result)


def test_detection_accepts_a_source_symlink_that_stays_inside_project_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = project / "source.py"
    source.write_text("from fastapi import FastAPI\n", encoding="utf-8")
    (project / "linked.py").symlink_to(source)
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump({
            "skills": [{
                "skill": "fastapi",
                "activation": {
                    "sourceImport": {"module": "fastapi", "extensions": [".py"]}
                },
                "companions": [],
                "selection": "additive",
                "priority": 100,
                "requiredWhenDetected": True,
            }]
        }),
        encoding="utf-8",
    )

    result = detect_technology_skills(project, ["linked.py"], registry, tmp_path / "skills", ["fastapi"])

    assert result.exit_code == 0
    assert result.result["loadouts"][0]["skills"] == ["fastapi"]
    assert result.result["loadouts"][0]["status"] == "READY"
