# MCP Agent Operations

`mcp-agent-ops` is a local stdio MCP server for deterministic agent-development operations that otherwise cause repeated shell and generated Python calls.

The initial service owns three capability groups:

- repository claims, worktree isolation, event journaling, archival, and contention reporting;
- reusable YAML and Markdown verification operations;
- structured discovery and on-demand reading of installed Agent Skills.

The domain packages are independent of FastMCP. The installed `mcp-agent-ops` command starts the FastMCP stdio server, while `mcp-agent-ops-claims` preserves a direct CLI surface for claim coordination and recovery.

The initial claim engine, technology detector, and Agent Skill validator are copied from the accepted `dev-methodology` implementations. See `docs/reference/copied-scripts.md` for exact provenance and compatibility coverage.

See `docs/reference/mcp-tools.md` for the complete small-call tool and resource surface.

## Development

Python 3.11 or newer and `uv` are required for development.

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```

## Local MCP configuration

Install once into an isolated tool environment:

```bash
uv tool install /absolute/path/to/mcp-agent-ops
```

Configure an MCP host to run:

```text
mcp-agent-ops
```

The server uses stdio by default. Configure readable skill roots through `MCP_AGENT_OPS_SKILL_ROOTS`, using the operating system path separator between roots. Configure the methodology-owned technology registry through `MCP_AGENT_OPS_DETECTION_REGISTRY`. Repository arguments remain explicit per tool call.

## State ownership

Claim registries and event journals live in each target repository's Git common directory. Skill files remain in their installed roots. The MCP process does not hold authoritative claim or skill-load state.
