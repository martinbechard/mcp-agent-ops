# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies the in-memory MCP tool and resource contract over all capability groups.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import asyncio
import json
import os
import subprocess
from pathlib import Path
from unittest import mock

import pytest
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams

from mcp_agent_ops.adapters.mcp.audit import ToolAuditLog, ToolAuditMiddleware
from mcp_agent_ops.adapters.mcp.server import create_server
from mcp_agent_ops.skill_catalog.catalog import SkillCatalog


def _initialize_repository(path: Path) -> None:
    path.mkdir()
    (path / "backlog").mkdir()
    (path / "README.md").write_text("baseline\n", encoding="utf-8")
    (path / "backlog" / "item.md").write_text("queued\n", encoding="utf-8")
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
        claim_tools = {tool.name: tool for tool in tools if tool.name in {"claim_acquire", "claim_extend"}}
        for tool in claim_tools.values():
            properties = tool.inputSchema["properties"]
            assert properties["project_files"]["type"] == "boolean"
            assert properties["backlog"]["type"] == "boolean"
            assert properties["all_files"]["type"] == "boolean"
            assert ".worktrees/<claim-id>" in properties["project_files"]["description"]
            assert "backlog omitted by sparse checkout" in properties["project_files"]["description"]
            assert "PRIMARY_REQUIRED" in properties["backlog"]["description"]
            assert "requires scope_reason" in properties["all_files"]["description"]
        assert "PRIMARY_REQUIRED" in (claim_tools["claim_acquire"].description or "")
        assert ".worktrees/<claim-id>" in (claim_tools["claim_acquire"].description or "")
        assert "backlog omitted" in (claim_tools["claim_acquire"].description or "")
        assert "all-files extension" in (claim_tools["claim_extend"].description or "")

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

        project_claim = await client.call_tool(
            "claim_acquire",
            {
                "repository": str(repository),
                "claim_id": "project-domain",
                "agent": "contract-test",
                "task": "project-domain",
                "root_task_id": "project-domain",
                "project_files": True,
                "scope_reason": "project implementation",
            },
        )
        assert project_claim.structured_content["result"]["claim"]["file_domain"] == "project_files"
        backlog_wait = await client.call_tool(
            "claim_acquire",
            {
                "repository": str(repository),
                "claim_id": "backlog-domain",
                "agent": "contract-test",
                "task": "backlog-domain",
                "root_task_id": "backlog-domain",
                "backlog": True,
            },
        )
        assert backlog_wait.structured_content["exit_code"] == 3
        assert backlog_wait.structured_content["result"]["outcome"] == "PRIMARY_REQUIRED"
        await client.call_tool(
            "claim_release",
            {"repository": str(repository), "claim_id": "project-domain", "no_change": True},
        )
        invalid_domains = await client.call_tool(
            "claim_acquire",
            {
                "repository": str(repository),
                "claim_id": "invalid-domains",
                "agent": "contract-test",
                "task": "invalid-domains",
                "root_task_id": "invalid-domains",
                "project_files": True,
                "backlog": True,
                "scope_reason": "invalid mixed domains",
            },
        )
        assert invalid_domains.structured_content["exit_code"] == 1
        assert invalid_domains.structured_content["result"]["outcome"] == "INVALID_SCOPE"
        assert (
            invalid_domains.structured_content["result"]["rejection"]["reason"]
            == "multiple_broad_file_domains"
        )
        all_files = await client.call_tool(
            "claim_acquire",
            {
                "repository": str(repository),
                "claim_id": "all-domains",
                "agent": "contract-test",
                "task": "all-domains",
                "root_task_id": "all-domains",
                "all_files": True,
                "scope_reason": "repository migration",
            },
        )
        assert all_files.structured_content["result"]["claim"]["file_domain"] == "all_files"
        await client.call_tool(
            "claim_release",
            {"repository": str(repository), "claim_id": "all-domains", "no_change": True},
        )

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


async def test_server_overlays_nested_project_skills_from_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    user_skills = tmp_path / "user-skills"
    project_skill = project / ".agents" / "skills" / "backend" / "example"
    project_skill.mkdir(parents=True)
    (project_skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Project example skill.\n---\n\n# Project\n",
        encoding="utf-8",
    )
    codex_skill = project / ".codex" / "skills" / "example"
    codex_skill.mkdir(parents=True)
    (codex_skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Codex project skill.\n---\n\n# Codex\n",
        encoding="utf-8",
    )
    _write_skill(user_skills)
    monkeypatch.chdir(project)
    server = create_server(
        [user_skills],
        workspace_roots=[tmp_path],
    )

    async with Client(server) as client:
        catalog = await client.call_tool("skill_list", {})
        loaded = await client.call_tool("skill_read", {"name": "example"})

    assert catalog.structured_content["skills"][0]["description"] == "Project example skill."
    assert catalog.structured_content["skills"][0]["shadowed_count"] == 2
    assert loaded.structured_content["content"].endswith("# Project\n")


def test_server_rejects_project_skill_root_symlink_escape(tmp_path: Path) -> None:
    project = tmp_path / "project"
    external_skills = tmp_path / "external-skills"
    (project / ".agents").mkdir(parents=True)
    external_skills.mkdir()
    (project / ".agents" / "skills").symlink_to(
        external_skills,
        target_is_directory=True,
    )

    with pytest.raises(ValueError, match="outside the project root"):
        create_server(skill_roots=[], workspace_roots=[tmp_path], project_root=project)


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


async def test_server_writes_digest_only_tool_audit_records(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    _write_skill(skills)
    audit_log = evidence / "mcp-audit.jsonl"
    server = create_server(
        [skills],
        audit_log=audit_log,
        audit_roots=[evidence],
    )

    async with Client(server) as client:
        await client.call_tool("skill_read", {"name": "example"})

    records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
    assert [record["status"] for record in records] == ["started", "completed"]
    assert {record["tool"] for record in records} == {"skill_read"}
    assert records[0]["callId"] == records[1]["callId"]
    assert set(records[0]) == {
        "schema",
        "version",
        "sequence",
        "callId",
        "tool",
        "status",
        "argumentsDigest",
    }
    assert set(records[1]) == {
        "schema",
        "version",
        "sequence",
        "callId",
        "tool",
        "status",
        "resultDigest",
    }
    assert len(records[0]["argumentsDigest"]) == 64
    assert len(records[1]["resultDigest"]) == 64
    serialized = json.dumps(records, sort_keys=True)
    assert "example" not in serialized
    assert "supporting guide" not in serialized
    assert str(tmp_path) not in serialized


def test_server_rejects_audit_log_outside_configured_audit_roots(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()

    with pytest.raises(ValueError, match="outside configured audit roots"):
        create_server(
            [],
            audit_log=tmp_path / "outside.jsonl",
            audit_roots=[evidence],
        )


@pytest.mark.parametrize("existing_kind", ["file", "symlink"])
def test_server_rejects_preexisting_audit_leaf(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    audit_log = evidence / "mcp-audit.jsonl"
    target = evidence / "target.jsonl"
    if existing_kind == "file":
        audit_log.write_text("existing\n", encoding="utf-8")
    else:
        audit_log.symlink_to(target.name)

    with pytest.raises(ValueError, match="new regular file"):
        create_server([], audit_log=audit_log, audit_roots=[evidence])

    assert not target.exists()


async def test_server_redacts_unknown_tool_names_from_audit(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    audit_log = evidence / "mcp-audit.jsonl"
    server = create_server([], audit_log=audit_log, audit_roots=[evidence])

    async with Client(server) as client:
        with pytest.raises(ToolError):
            await client.call_tool("PROMPT_SECRET_/private/example", {})

    audit = audit_log.read_text(encoding="utf-8")
    records = [json.loads(line) for line in audit.splitlines()]
    assert {record["tool"] for record in records} == {"unknown_tool"}
    assert all("outcome" not in record for record in records)
    assert "PROMPT_SECRET" not in audit
    assert "/private/example" not in audit


async def test_server_audit_sequences_concurrent_calls(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    _write_skill(skills)
    audit_log = evidence / "mcp-audit.jsonl"
    server = create_server([skills], audit_log=audit_log, audit_roots=[evidence])

    async with Client(server) as client:
        await asyncio.gather(
            *(client.call_tool("skill_list", {}) for _ in range(8))
        )

    records = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
    assert [record["sequence"] for record in records] == list(range(1, 17))
    starts = {
        record["callId"]: record["tool"]
        for record in records
        if record["status"] == "started"
    }
    terminals = {
        record["callId"]: record["tool"]
        for record in records
        if record["status"] in {"completed", "failed"}
    }
    assert starts == terminals
    assert len(starts) == 8


def test_audit_log_keeps_writing_to_exclusively_opened_file(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    moved_path = tmp_path / "moved.jsonl"
    audit = ToolAuditLog(audit_path)
    call_id = audit.start("skill_list", {})
    audit_path.rename(moved_path)
    audit_path.write_text("replacement\n", encoding="utf-8")

    audit.finish(call_id, "skill_list", "completed", {"ok": True})

    assert len(moved_path.read_text(encoding="utf-8").splitlines()) == 2
    assert audit_path.read_text(encoding="utf-8") == "replacement\n"


def test_shared_audit_log_separates_process_streams_under_one_file(tmp_path: Path) -> None:
    audit_path = tmp_path / "shared-audit.jsonl"
    session_id = "a" * 32
    first = ToolAuditLog(audit_path, shared=True, session_id=session_id)
    second = ToolAuditLog(audit_path, shared=True, session_id=session_id)

    first_call = first.start("skill_list", {})
    second_call = second.start("claim_status", {})
    first.finish(first_call, "skill_list", "completed", {"ok": True})
    second.finish(second_call, "claim_status", "completed", {"ok": True})

    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert {record["version"] for record in records} == {2}
    assert {record["sessionId"] for record in records} == {session_id}
    streams = {record["streamId"] for record in records}
    assert len(streams) == 2
    for stream in streams:
        stream_records = [record for record in records if record["streamId"] == stream]
        assert [record["sequence"] for record in stream_records] == [1, 2]
        assert [record["status"] for record in stream_records] == [
            "started",
            "completed",
        ]


def test_shared_audit_rejects_preexisting_group_readable_file(tmp_path: Path) -> None:
    audit_path = tmp_path / "shared-audit.jsonl"
    audit_path.write_text("", encoding="utf-8")
    audit_path.chmod(0o640)

    with pytest.raises(ValueError, match="owner-only"):
        ToolAuditLog(audit_path, shared=True, session_id="a" * 32)


@pytest.mark.parametrize("existing_kind", ["fifo", "hard-link"])
def test_shared_audit_rejects_non_regular_or_linked_leaf(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    audit_path = tmp_path / "shared-audit.jsonl"
    if existing_kind == "fifo":
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(audit_path, mode=0o600)
    else:
        target = tmp_path / "target.jsonl"
        target.write_text("", encoding="utf-8")
        target.chmod(0o600)
        os.link(target, audit_path)

    with pytest.raises(ValueError, match="regular file"):
        ToolAuditLog(audit_path, shared=True, session_id="a" * 32)


@pytest.mark.parametrize("session_id", [None, "A" * 32, "a" * 31])
def test_shared_audit_requires_canonical_session_identity(
    tmp_path: Path,
    session_id: str | None,
) -> None:
    with pytest.raises(ValueError, match="session identity"):
        ToolAuditLog(
            tmp_path / f"audit-{session_id or 'missing'}.jsonl",
            shared=True,
            session_id=session_id,
        )


def test_audit_session_identity_requires_shared_mode(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only for shared"):
        ToolAuditLog(tmp_path / "audit.jsonl", session_id="a" * 32)


def test_shared_audit_server_requires_log_path() -> None:
    with pytest.raises(ValueError, match="requires an audit log path"):
        create_server([], audit_shared=True, audit_session_id="a" * 32)


def test_server_rejects_invalid_shared_audit_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_AGENT_OPS_AUDIT_SHARED", "sometimes")
    with pytest.raises(ValueError, match="must be true or false"):
        create_server([])


async def test_server_instances_share_one_evaluation_audit(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    audit_log = evidence / "mcp-audit.jsonl"
    first = create_server(
        [],
        audit_log=audit_log,
        audit_roots=[evidence],
        audit_shared=True,
        audit_session_id="b" * 32,
    )
    second = create_server(
        [],
        audit_log=audit_log,
        audit_roots=[evidence],
        audit_shared=True,
        audit_session_id="b" * 32,
    )

    async with Client(first) as first_client, Client(second) as second_client:
        await asyncio.gather(
            first_client.call_tool("skill_list", {}),
            second_client.call_tool("skill_list", {}),
        )

    records = [
        json.loads(line)
        for line in audit_log.read_text(encoding="utf-8").splitlines()
    ]
    assert len({record["streamId"] for record in records}) == 2
    assert all(record["version"] == 2 for record in records)
    assert {
        record.get("outcome")
        for record in records
        if record["status"] == "completed"
    } == {"EMPTY"}


async def test_server_audit_records_bounded_domain_outcomes(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    skills = tmp_path / "skills"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    _initialize_repository(repository)
    _write_skill(skills)
    (repository / "valid.yaml").write_text("value: true\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repository), "add", "valid.yaml"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "commit", "-m", "add yaml"],
        check=True,
        capture_output=True,
        text=True,
    )
    audit_log = evidence / "mcp-audit.jsonl"
    server = create_server(
        [skills],
        workspace_roots=[tmp_path],
        audit_log=audit_log,
        audit_roots=[evidence],
        audit_shared=True,
        audit_session_id="c" * 32,
    )

    async with Client(server) as client:
        await client.call_tool("skill_list", {})
        await client.call_tool(
            "claim_acquire",
            {
                "repository": str(repository),
                "claim_id": "audit-outcome",
                "agent": "contract-test",
                "task": "audit-outcome",
                "root_task_id": "audit-outcome",
                "files": ["README.md"],
            },
        )
        await client.call_tool(
            "verify_yaml",
            {
                "repository_root": str(repository),
                "paths": ["valid.yaml"],
            },
        )
        await client.call_tool(
            "claim_release",
            {
                "repository": str(repository),
                "claim_id": "audit-outcome",
                "no_change": True,
            },
        )

    outcomes = {
        record["tool"]: record.get("outcome")
        for record in (
            json.loads(line)
            for line in audit_log.read_text(encoding="utf-8").splitlines()
        )
        if record["status"] == "completed"
    }
    assert outcomes == {
        "skill_list": "CATALOG",
        "claim_acquire": "PRIMARY",
        "verify_yaml": "OK",
        "claim_release": "RELEASED",
    }


async def test_shared_audit_records_bounded_skill_load_outcomes(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    _write_skill(skills)
    audit_log = evidence / "mcp-audit.jsonl"
    server = create_server(
        [skills],
        audit_log=audit_log,
        audit_roots=[evidence],
        audit_shared=True,
        audit_session_id="d" * 32,
    )

    async with Client(server) as client:
        await client.call_tool("skill_load", {"names": ["example"]})
        await client.call_tool("skill_load", {"names": ["missing"]})
        await client.call_tool(
            "skill_resource_load",
            {
                "requests": [{
                    "skill_name": "example",
                    "resource_path": "references/guide.md",
                }]
            },
        )
        await client.call_tool(
            "skill_resource_load",
            {
                "requests": [{
                    "skill_name": "example",
                    "resource_path": "missing.md",
                }]
            },
        )

    audit = audit_log.read_text(encoding="utf-8")
    completed = [
        (record["tool"], record.get("outcome"))
        for record in (json.loads(line) for line in audit.splitlines())
        if record["status"] == "completed"
    ]
    assert completed == [
        ("skill_load", "LOADED"),
        ("skill_load", "REJECTED"),
        ("skill_resource_load", "LOADED"),
        ("skill_resource_load", "REJECTED"),
    ]
    assert "supporting guide" not in audit
    assert "references/guide.md" not in audit
    assert '"missing"' not in audit


async def test_shared_audit_records_bounded_validation_and_refresh_outcomes(
    tmp_path: Path,
) -> None:
    skills = tmp_path / "skills"
    empty_skills = tmp_path / "empty-skills"
    evidence = tmp_path / "evidence"
    empty_skills.mkdir()
    evidence.mkdir()
    _write_skill(skills)
    audit_log = evidence / "mcp-audit.jsonl"
    populated_server = create_server(
        [skills],
        audit_log=audit_log,
        audit_roots=[evidence],
        audit_shared=True,
        audit_session_id="f" * 32,
    )
    empty_server = create_server(
        [empty_skills],
        audit_log=audit_log,
        audit_roots=[evidence],
        audit_shared=True,
        audit_session_id="f" * 32,
    )

    async with Client(populated_server) as client:
        await client.call_tool("skill_refresh", {})
        await client.call_tool(
            "skill_validate",
            {"paths": [str(skills / "example")]},
        )
        invalid_skill = skills / "private-invalid-skill"
        invalid_skill.mkdir()
        (invalid_skill / "SKILL.md").write_text(
            "---\nname: private_invalid\ndescription: <private-validation-marker>.\n---\n",
            encoding="utf-8",
        )
        await client.call_tool(
            "skill_validate",
            {"paths": [str(invalid_skill)]},
        )
        with pytest.raises(
            ToolError,
            match="At least one skill validation path is required",
        ):
            await client.call_tool("skill_validate", {"paths": []})

    async with Client(empty_server) as client:
        await client.call_tool("skill_refresh", {})

    audit = audit_log.read_text(encoding="utf-8")
    terminal = [
        (record["tool"], record["status"], record.get("outcome"))
        for record in (json.loads(line) for line in audit.splitlines())
        if record["status"] != "started"
    ]
    assert terminal == [
        ("skill_refresh", "completed", "CATALOG"),
        ("skill_validate", "completed", "VALID"),
        ("skill_validate", "completed", "FINDINGS"),
        ("skill_validate", "failed", "ERROR"),
        ("skill_refresh", "completed", "EMPTY"),
    ]
    assert "example" not in audit
    assert "private-invalid-skill" not in audit
    assert "private-validation-marker" not in audit
    assert "frontmatter name must use" not in audit
    assert "At least one skill validation path is required" not in audit


async def test_shared_audit_distinguishes_empty_deterministic_operations(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    skills = tmp_path / "skills"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    _initialize_repository(repository)
    skills.mkdir()
    registry = tmp_path / "registry.yaml"
    registry.write_text("schemaVersion: 1\nskills: []\n", encoding="utf-8")
    audit_log = evidence / "mcp-audit.jsonl"
    server = create_server(
        [skills],
        detection_registry=registry,
        workspace_roots=[tmp_path],
        audit_log=audit_log,
        audit_roots=[evidence],
        audit_shared=True,
        audit_session_id="e" * 32,
    )

    async with Client(server) as client:
        await client.call_tool("skill_list", {})
        await client.call_tool(
            "verify_yaml",
            {"repository_root": str(repository), "paths": []},
        )
        await client.call_tool(
            "detect_technology_skills",
            {"project_root": str(repository), "scopes": []},
        )

    outcomes = [
        record.get("outcome")
        for record in (
            json.loads(line)
            for line in audit_log.read_text(encoding="utf-8").splitlines()
        )
        if record["status"] == "completed"
    ]
    assert outcomes == ["EMPTY", "EMPTY", "EMPTY"]


async def test_audit_middleware_preserves_dispatch_failure_and_success() -> None:
    context = MiddlewareContext(
        message=CallToolRequestParams(name="skill_list", arguments={})
    )
    failed_audit = mock.Mock(spec=ToolAuditLog)
    failed_audit.start.return_value = "1"
    failed_audit.shared = False
    failed_middleware = ToolAuditMiddleware(failed_audit, frozenset({"skill_list"}))

    async def fail_dispatch(
        _context: MiddlewareContext[CallToolRequestParams],
    ) -> ToolResult:
        raise RuntimeError("dispatch failed")

    with pytest.raises(RuntimeError, match="dispatch failed"):
        await failed_middleware.on_call_tool(context, fail_dispatch)
    failed_audit.finish.assert_called_once_with(
        "1", "skill_list", "failed", {"errorType": "RuntimeError"}, None
    )

    completed = ToolResult(structured_content={"ok": True})
    completed_audit = mock.Mock(spec=ToolAuditLog)
    completed_audit.start.return_value = "2"
    completed_audit.shared = False
    completed_audit.finish.side_effect = OSError("audit unavailable")
    completed_middleware = ToolAuditMiddleware(
        completed_audit,
        frozenset({"skill_list"}),
    )

    async def complete_dispatch(
        _context: MiddlewareContext[CallToolRequestParams],
    ) -> ToolResult:
        return completed

    assert await completed_middleware.on_call_tool(context, complete_dispatch) is completed


async def test_audit_middleware_fails_closed_before_dispatch() -> None:
    context = MiddlewareContext(
        message=CallToolRequestParams(name="skill_list", arguments={})
    )
    audit = mock.Mock(spec=ToolAuditLog)
    audit.start.side_effect = OSError("audit unavailable")
    middleware = ToolAuditMiddleware(audit, frozenset({"skill_list"}))
    dispatched = False

    async def dispatch(
        _context: MiddlewareContext[CallToolRequestParams],
    ) -> ToolResult:
        nonlocal dispatched
        dispatched = True
        return ToolResult()

    with pytest.raises(OSError, match="audit unavailable"):
        await middleware.on_call_tool(context, dispatch)
    assert dispatched is False
