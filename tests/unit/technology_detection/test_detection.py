# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies copied technology-skill detection through its framework-independent service.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

import yaml

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
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = detect_technology_skills(project, ["main.py"], registry, skills, ["fastapi"])

    assert result.exit_code == 0
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

