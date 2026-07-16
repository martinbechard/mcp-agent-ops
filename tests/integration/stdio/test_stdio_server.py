# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies initialization and tool invocation through a real stdio MCP subprocess.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def test_real_stdio_server_initializes_lists_and_invokes_tools(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Stdio example.\n---\n\n# Example\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["MCP_AGENT_OPS_SKILL_ROOTS"] = str(tmp_path / "skills")
    environment["MCP_AGENT_OPS_AUDIT_LOG"] = str(tmp_path / "mcp-audit.jsonl")
    environment["MCP_AGENT_OPS_AUDIT_ROOTS"] = str(tmp_path)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "mcp_agent_ops"],
        env=environment,
        cwd=str(tmp_path),
    )

    async with Client(transport, timeout=15) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert "skill_list" in names
        assert "skill_load" in names
        assert "skill_refresh" in names
        result = await client.call_tool("skill_read", {"name": "example"})
        assert result.structured_content["name"] == "example"
        assert "entry" not in result.structured_content
        assert "path" not in result.structured_content
        first = await client.call_tool("skill_load", {"names": ["example"]})
        (skill / "SKILL.md").write_text(
            "---\nname: example\ndescription: Stdio example.\n---\n\n# Changed\n",
            encoding="utf-8",
        )
        unchanged = await client.call_tool("skill_load", {"names": ["example"]})
        assert unchanged.structured_content == first.structured_content
        await client.call_tool("skill_refresh", {})
        refreshed = await client.call_tool("skill_load", {"names": ["example"]})
        assert refreshed.structured_content["skills"][0]["content"].endswith("# Changed\n")

    audit = (tmp_path / "mcp-audit.jsonl").read_text(encoding="utf-8")
    assert '"tool":"skill_load"' in audit
    assert '"status":"completed"' in audit
    assert '"outcome"' not in audit
    assert "Stdio example" not in audit


async def test_real_stdio_servers_share_one_session_bound_audit(tmp_path: Path) -> None:
    skill = tmp_path / "skills" / "example"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: example\ndescription: Shared audit example.\n---\n\n# Example\n",
        encoding="utf-8",
    )
    audit_path = tmp_path / "shared-audit.jsonl"
    session_id = "d" * 32
    environment = os.environ.copy()
    environment["MCP_AGENT_OPS_SKILL_ROOTS"] = str(tmp_path / "skills")
    environment["MCP_AGENT_OPS_AUDIT_LOG"] = str(audit_path)
    environment["MCP_AGENT_OPS_AUDIT_ROOTS"] = str(tmp_path)
    environment["MCP_AGENT_OPS_AUDIT_SHARED"] = "true"
    environment["MCP_AGENT_OPS_AUDIT_SESSION_ID"] = session_id

    def transport() -> StdioTransport:
        return StdioTransport(
            command=sys.executable,
            args=["-m", "mcp_agent_ops"],
            env=environment,
            cwd=str(tmp_path),
        )

    async with (
        Client(transport(), timeout=15) as first,
        Client(transport(), timeout=15) as second,
    ):
        first_result, second_result = await asyncio.gather(
            first.call_tool("skill_list", {}),
            second.call_tool("skill_list", {}),
        )
        assert first_result.structured_content["skills"][0]["name"] == "example"
        assert second_result.structured_content["skills"][0]["name"] == "example"

    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    stream_ids = {record["streamId"] for record in records}
    assert len(stream_ids) == 2
    assert {record["sessionId"] for record in records} == {session_id}
    for stream_id in stream_ids:
        stream_records = [
            record for record in records if record["streamId"] == stream_id
        ]
        assert [record["sequence"] for record in stream_records] == [1, 2]
        assert [record["status"] for record in stream_records] == [
            "started",
            "completed",
        ]
        assert stream_records[-1]["outcome"] == "CATALOG"
