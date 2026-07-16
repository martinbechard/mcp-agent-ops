# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies initialization and tool invocation through a real stdio MCP subprocess.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

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
