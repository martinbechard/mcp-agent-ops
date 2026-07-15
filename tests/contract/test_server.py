# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies the in-memory MCP tool and resource contract over all capability groups.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import json
import subprocess
from pathlib import Path

from fastmcp import Client

from mcp_agent_ops.adapters.mcp.server import create_server


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
    server = create_server([skills])

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
            "skill_validate",
            "detect_technology_skills",
        } <= names

        status = await client.call_tool("claim_status", {"repository": str(repository)})
        assert status.structured_content["exit_code"] == 0
        assert status.structured_content["result"]["outcome"] == "STATUS"
        assert status.structured_content["result"]["claims"] == []

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
        loaded = await client.call_tool("skill_read", {"name": "example"})
        assert loaded.structured_content["content"].endswith("Use it.\n")
        resource = await client.call_tool(
            "skill_read_resource",
            {"name": "example", "resource_path": "references/guide.md"},
        )
        assert resource.structured_content["content"] == "supporting guide\n"
        validation = await client.call_tool("skill_validate", {"paths": [str(skills / "example")]})
        assert validation.structured_content["ok"] is True


async def test_server_publishes_skill_catalog_and_complete_skill_resources(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    _write_skill(skills)
    server = create_server([skills])

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
    server = create_server([skills], detection_registry=registry)

    async with Client(server) as client:
        detected = await client.call_tool(
            "detect_technology_skills",
            {"project_root": str(project), "scopes": ["."]},
        )

    assert detected.structured_content["exit_code"] == 0
    assert detected.structured_content["result"]["loadouts"][0]["status"] == "NO_VARIANT"
