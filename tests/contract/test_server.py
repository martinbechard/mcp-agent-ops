# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies the in-memory MCP tool and resource contract over all capability groups.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_agent_ops.adapters.mcp.server import create_server
from mcp_agent_ops.skill_catalog.catalog import SkillCatalog


def _initialize_repository(path: Path) -> None:
    path.mkdir()
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    for arguments in (
        ("init",),
        ("config", "user.email", "test@example.invalid"),
        ("config", "user.name", "MCP Test"),
        ("add", "."),
        ("commit", "-m", "baseline"),
    ):
        subprocess.run(["git", "-C", str(path), *arguments], check=True, capture_output=True, text=True)


def _write_skill(root: Path) -> None:
    skill = root / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Example MCP skill.\n---\n\n# Example\n\nUse it.\n",
        encoding="utf-8",
    )
    references = skill / "references"
    references.mkdir()
    (references / "guide.md").write_text("supporting guide\n", encoding="utf-8")


async def test_server_publishes_small_named_tools_and_structured_results(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    skills = tmp_path / "skills"
    _initialize_repository(repository)
    _write_skill(skills)
    server = create_server([skills], workspace_roots=[tmp_path])

    async with Client(server) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert {
            "claim_status",
            "claim_acquire",
            "claim_extend",
            "claim_heartbeat",
            "claim_release",
            "claim_maintain_journal",
            "claim_report",
            "verify_yaml",
            "verify_markdown_links",
            "skill_list",
            "skill_read",
            "skill_read_resource",
            "skill_load",
            "skill_resource_load",
            "skill_refresh",
            "skill_validate",
            "detect_technology_skills",
        } <= names

        status = await client.call_tool("claim_status", {"repository": str(repository)})
        assert status.structured_content["exit_code"] == 0
        assert status.structured_content["result"]["outcome"] == "STATUS"
        assert status.structured_content["result"]["claims"] == []
        report = await client.call_tool("claim_report", {"repository": str(repository)})
        assert report.structured_content["exit_code"] == 0
        assert report.structured_content["result"]["schema_version"] == 1

        acquired = await client.call_tool(
            "claim_acquire",
            {
                "repository": str(repository),
                "claim_id": "contract-claim",
                "agent": "contract-test",
                "task": "contract-test",
                "root_task_id": "contract-claim",
                "files": ["README.md"],
            },
        )
        assert acquired.structured_content["result"]["outcome"] == "PRIMARY"
        released = await client.call_tool(
            "claim_release",
            {"repository": str(repository), "claim_id": "contract-claim", "no_change": True},
        )
        assert released.structured_content["result"]["outcome"] == "RELEASED"

        (repository / "invalid.yaml").write_text("same: one\nsame: two\n", encoding="utf-8")
        verified = await client.call_tool(
            "verify_yaml",
            {"repository_root": str(repository), "paths": ["invalid.yaml"]},
        )
        assert verified.structured_content["ok"] is False
        assert verified.structured_content["findings"][0]["code"] == "duplicate_key"

        catalog = await client.call_tool("skill_list", {})
        assert catalog.structured_content["skills"][0]["name"] == "example"
        assert "roots" not in catalog.structured_content
        assert "path" not in catalog.structured_content["skills"][0]
        assert "root" not in catalog.structured_content["skills"][0]
        loaded = await client.call_tool("skill_read", {"name": "example"})
        assert loaded.structured_content["content"].endswith("Use it.\n")
        assert "entry" not in loaded.structured_content
        assert "path" not in loaded.structured_content
        resource = await client.call_tool(
            "skill_read_resource",
            {"name": "example", "resource_path": "references/guide.md"},
        )
        assert resource.structured_content["content"] == "supporting guide\n"
        resources = await client.call_tool(
            "skill_resource_load",
            {
                "requests": [{
                    "skill_name": "example",
                    "resource_path": "references/guide.md",
                }]
            },
        )
        assert resources.structured_content["ok"] is True
        assert resources.structured_content["resources"][0]["content"] == "supporting guide\n"
        validation = await client.call_tool("skill_validate", {"paths": [str(skills / "example")]})
        assert validation.structured_content["ok"] is True


async def test_server_reuses_one_catalog_snapshot_until_explicit_refresh(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills)
    skill_file = skills / "example" / "SKILL.md"
    original_builder = SkillCatalog.from_roots
    with mock.patch.object(
        SkillCatalog,
        "from_roots",
        wraps=original_builder,
    ) as build_catalog:
        server = create_server([skills])
        async with Client(server) as client:
            await client.call_tool("skill_list", {})
            first = await client.call_tool("skill_load", {"names": ["example"]})
            await client.call_tool("skill_read", {"name": "example"})
            assert build_catalog.call_count == 1

            skill_file.write_text(
                "---\nname: example\ndescription: Example MCP skill.\n---\n\n# Example\n\nChanged.\n",
                encoding="utf-8",
            )
            unchanged = await client.call_tool("skill_load", {"names": ["example"]})
            assert unchanged.structured_content == first.structured_content

            await client.call_tool("skill_refresh", {})
            refreshed = await client.call_tool("skill_load", {"names": ["example"]})
            assert build_catalog.call_count == 2

    assert refreshed.structured_content["skills"][0]["content"].endswith("Changed.\n")
    assert (
        refreshed.structured_content["catalog_revision"]
        != first.structured_content["catalog_revision"]
    )


async def test_server_publishes_skill_catalog_and_complete_skill_resources(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills)
    server = create_server([skills], workspace_roots=[tmp_path])

    async with Client(server) as client:
        resources = await client.list_resources()
        assert "skill://catalog" in {str(resource.uri) for resource in resources}
        templates = await client.list_resource_templates()
        assert "skill://{name}" in {str(template.uriTemplate) for template in templates}

        catalog_content = await client.read_resource("skill://catalog")
        catalog = json.loads(catalog_content[0].text)
        assert catalog["skills"][0]["name"] == "example"
        skill_content = await client.read_resource("skill://example")
        assert skill_content[0].text.endswith("Use it.\n")


async def test_server_runs_configured_technology_detection_without_script_arguments(tmp_path: Path) -> None:
    project = tmp_path / "project"
    skills = tmp_path / "skills"
    project.mkdir()
    (project / "README.md").write_text("project\n", encoding="utf-8")
    _write_skill(skills)
    registry = tmp_path / "registry.yaml"
    registry.write_text("skills: []\n", encoding="utf-8")
    server = create_server(
        [skills],
        detection_registry=registry,
        workspace_roots=[tmp_path],
    )

    async with Client(server) as client:
        detected = await client.call_tool(
            "detect_technology_skills",
            {"project_root": str(project), "scopes": ["."]},
        )
        registry.write_text(
            yaml.safe_dump({
                "skills": [{
                    "skill": "example",
                    "activation": {"fileExtension": ".md"},
                    "companions": [],
                    "selection": "additive",
                    "priority": 100,
                    "requiredWhenDetected": True,
                }]
            }),
            encoding="utf-8",
        )
        unchanged = await client.call_tool(
            "detect_technology_skills",
            {"project_root": str(project), "scopes": ["."]},
        )

    assert detected.structured_content["exit_code"] == 0
    assert detected.structured_content["result"]["loadouts"][0]["status"] == "NO_VARIANT"
    assert detected.structured_content["result"]["projectRoot"] == "."
    assert "skillsRoot" not in detected.structured_content["result"]["runtimeSkillCatalog"]
    assert str(project) not in json.dumps(detected.structured_content)
    assert str(skills) not in json.dumps(detected.structured_content)
    assert unchanged.structured_content == detected.structured_content


async def test_server_rejects_model_paths_outside_configured_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    repository = allowed / "repository"
    skills = allowed / "skills"
    allowed.mkdir()
    _initialize_repository(repository)
    _initialize_repository(outside)
    _write_skill(skills)
    registry = allowed / "registry.yaml"
    registry.write_text("skills: []\n", encoding="utf-8")
    server = create_server(
        [skills],
        detection_registry=registry,
        workspace_roots=[allowed],
    )

    async with Client(server) as client:
        with pytest.raises(ToolError, match="outside configured workspace roots"):
            await client.call_tool("claim_status", {"repository": str(outside)})
        with pytest.raises(ToolError, match="outside configured workspace roots"):
            await client.call_tool(
                "verify_yaml",
                {"repository_root": str(outside), "paths": ["README.md"]},
            )
        with pytest.raises(ToolError, match="outside configured skill roots"):
            await client.call_tool("skill_validate", {"paths": [str(outside)]})
        with pytest.raises(ToolError, match="outside configured workspace roots"):
            await client.call_tool(
                "detect_technology_skills",
                {"project_root": str(outside), "scopes": ["."]},
            )
        with pytest.raises(ToolError, match="outside configured workspace roots"):
            await client.call_tool(
                "claim_acquire",
                {
                    "repository": str(repository),
                    "claim_id": "escape",
                    "agent": "contract-test",
                    "task": "escape",
                    "root_task_id": "escape",
                    "files": ["README.md"],
                    "worktree_path": str(outside / "worktree"),
                },
            )


async def test_server_rejects_nested_skill_validation_symlink_escape_without_path_leak(
    tmp_path: Path,
) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (external / "SKILL.md").write_text(
        "---\nname: linked\ndescription: External skill.\n---\n",
        encoding="utf-8",
    )
    (skills / "linked").symlink_to(external, target_is_directory=True)
    server = create_server([skills], workspace_roots=[tmp_path])

    async with Client(server) as client:
        result = await client.call_tool("skill_validate", {"paths": [str(skills)]})

    assert result.structured_content["ok"] is False
    assert result.structured_content["findings"] == [{
        "path": "linked/SKILL.md",
        "message": "path resolves outside configured skill roots",
    }]
    assert str(tmp_path) not in json.dumps(result.structured_content)


@pytest.mark.parametrize("escape_kind", ["malformed", "symlink"])
async def test_server_catalog_failures_do_not_expose_configured_paths(
    tmp_path: Path,
    escape_kind: str,
) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    if escape_kind == "malformed":
        skill = skills / "invalid"
        skill.mkdir()
        (skill / "SKILL.md").write_text("# Missing frontmatter\n", encoding="utf-8")
    else:
        external = tmp_path / "external"
        _write_skill(external)
        (skills / "example").symlink_to(external / "example", target_is_directory=True)
    server = create_server([skills])

    async with Client(server) as client:
        with pytest.raises(ToolError) as captured:
            await client.call_tool("skill_list", {})

    assert "Configured skill catalog is invalid" in str(captured.value)
    assert str(tmp_path) not in str(captured.value)


async def test_server_detection_registry_failures_do_not_expose_configured_paths(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    skills = tmp_path / "skills"
    project.mkdir()
    _write_skill(skills)
    registry = tmp_path / "registry.yaml"
    registry.write_text("- not-a-mapping\n", encoding="utf-8")
    server = create_server(
        [skills],
        detection_registry=registry,
        workspace_roots=[tmp_path],
    )

    async with Client(server) as client:
        with pytest.raises(ToolError) as captured:
            await client.call_tool(
                "detect_technology_skills",
                {"project_root": str(project), "scopes": ["."]},
            )

    assert "Configured technology detection registry is invalid" in str(captured.value)
    assert str(tmp_path) not in str(captured.value)
