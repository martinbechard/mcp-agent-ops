# Project Taxonomy

## Conventions

- Classify files by responsibility rather than extension.
- Keep domain behavior independent of MCP and CLI adapters.
- Place executable product code under `src/mcp_agent_ops`.
- Mirror source-domain packages under `tests/unit`.
- Keep runtime repositories, claim registries, journals, and installed skill roots outside this repository.
- Extend this taxonomy before introducing a file category that does not fit below.

## Top-Level Folder Principles

- `src/` contains installable product code.
- `tests/` contains automated behavioral evidence.
- `docs/` contains durable requirements, design, and reference material.
- `.github/` contains hosted development automation.
- Top-level files describe installation, licensing, contribution constraints, and package metadata.

## Categories

### Product Domain Modules

- **Purpose:** Framework-independent claims, verification, and skill-catalog behavior.
- **Signals:** Code is callable without starting an MCP server or parsing a CLI command.
- **Filename pattern:** `src/mcp_agent_ops/<domain>/*.py`
- **Tests location:** `tests/unit/<domain>/test_*.py`
- **Example:** `src/mcp_agent_ops/skill_catalog/catalog.py`

### MCP Adapter

- **Purpose:** FastMCP tool and resource declarations that translate protocol inputs and outputs to domain calls.
- **Signals:** Imports FastMCP or MCP protocol types.
- **Filename pattern:** `src/mcp_agent_ops/adapters/mcp/*.py`
- **Tests location:** `tests/contract/test_*.py`
- **Example:** `src/mcp_agent_ops/adapters/mcp/server.py`

### CLI Adapter

- **Purpose:** Installed command entry points and command-line translation over domain behavior.
- **Signals:** Parses command-line arguments or defines a console-script entry point.
- **Filename pattern:** `src/mcp_agent_ops/adapters/cli/*.py`
- **Tests location:** `tests/compatibility/test_*.py`
- **Example:** `src/mcp_agent_ops/adapters/cli/claims.py`

### Unit Tests

- **Purpose:** Focused behavior and failure-boundary tests for one domain module.
- **Signals:** Does not require a protocol transport or external long-running service.
- **Filename pattern:** `tests/unit/<domain>/test_*.py`
- **Mirrors:** `src/mcp_agent_ops/<domain>`

### Contract Tests

- **Purpose:** MCP schema, tool, resource, and structured-result compatibility.
- **Signals:** Uses an in-memory MCP client or inspects published protocol definitions.
- **Filename pattern:** `tests/contract/test_*.py`

### Compatibility Tests

- **Purpose:** Preserve behavior and stable outcomes from an existing public command or data format.
- **Signals:** Uses black-box fixtures, stable exit codes, or legacy-format expectations.
- **Filename pattern:** `tests/compatibility/test_*.py`

### Integration Tests

- **Purpose:** Verify process, transport, concurrency, and real filesystem interactions.
- **Signals:** Starts subprocesses, creates Git worktrees, or exercises stdio.
- **Filename pattern:** `tests/integration/<boundary>/test_*.py`
- **Example:** `tests/integration/concurrency/test_claim_contention.py`

### Test Fixtures

- **Purpose:** Stable input and expected-output artifacts used by automated tests.
- **Signals:** Data is not imported as executable product code.
- **Filename pattern:** `tests/fixtures/<domain>/**`

### Requirements

- **Purpose:** Durable functional and technical requirements.
- **Signals:** Defines externally observable behavior or system constraints.
- **Filename pattern:** `docs/requirements/functional/*.md` or `docs/requirements/technical/*.md`

### Design

- **Purpose:** Architectural and component-level implementation decisions.
- **Signals:** Defines boundaries, ownership, state, flows, or failure handling.
- **Filename pattern:** `docs/design/high-level/*.md` or `docs/design/components/*.md`

### Reference

- **Purpose:** Stable operator-facing schemas, commands, and compatibility tables.
- **Signals:** Describes an implemented interface without owning requirements or design decisions.
- **Filename pattern:** `docs/reference/*.md`

### Hosted Automation

- **Purpose:** Continuous integration and hosted repository workflows.
- **Signals:** Runs in GitHub Actions.
- **Filename pattern:** `.github/workflows/*.yml`

### Top-Level Project Metadata

- **Purpose:** Installation, licensing, package metadata, and repository-wide instructions.
- **Signals:** Applies to the complete repository or packaging system.
- **Filename pattern:** Fixed conventional names such as `README.md`, `LICENSE`, `AGENTS.md`, `pyproject.toml`, and `uv.lock`.

## Change Log

- 2026-07-15: Established the initial standalone MCP agent-operations taxonomy.
