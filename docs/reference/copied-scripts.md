# Copied Script Provenance

The first release deliberately copies accepted scripts from `dev-methodology` so the MCP project can expose simpler model-facing calls without reimplementing proven behavior.

Current claim-engine, state-layout, and migration authority: `dev-methodology` commit `50850c6`.

| New project file | Source file | Compatibility evidence |
|---|---|---|
| `src/mcp_agent_ops/claims/engine.py` | `skills/agent-claim-command/scripts/claim.py` | `tests/compatibility/test_claim_cli.py` |
| `src/mcp_agent_ops/technology_detection/engine.py` | `skills/detect-technology-skills/scripts/detect.py` | `tests/unit/technology_detection/test_detection.py` |
| `src/mcp_agent_ops/skill_validation/engine.py` | `scripts/validate-agent-skills.py` | `tests/unit/skill_validation/test_validation.py` |

The claim engine retains the accepted command behavior and adds a context-local structured dispatch boundary used by MCP without standard-output capture. Its registry locking uses a cross-platform domain helper rather than the source script's direct POSIX `fcntl` calls; updates lock the registry itself and preserve its file identity so Windows and POSIX processes share the same disk-authoritative contract. Every checkout resolves that registry and its journal beneath the primary worktree's `.codex/agent-claim` directory. Empty legacy state migrates on the first mutation to the exact state-layout-version-two marker and incompatible legacy marker types; live legacy claims permit only exact release, and split or incomplete state returns the same structured stop through CLI and MCP. Work-item activity, resource deadline and extension evidence, release disposition, reset, and work-item reporting remain command-compatible. The technology detector and skill validator retain their existing adapter boundaries.

The methodology integration keeps the existing scripts as portability fallbacks while making this service the preferred deterministic operations layer. Future behavioral changes must either remain compatible with both surfaces or explicitly update their ownership and compatibility contract.
