# Copied Script Provenance

The first release deliberately copies accepted scripts from `dev-methodology` so the MCP project can expose simpler model-facing calls without reimplementing proven behavior.

Current claim-engine source authority: `dev-methodology` commit `fb04b6a78737d0540f2ef22091208584554d4969`.

Claim-state layout and migration authority: `dev-methodology` commit `a84d2f734d5d67ce8e767c2ea49cdd26e52d0ec4`.

| New project file | Source file | Compatibility evidence |
|---|---|---|
| `src/mcp_agent_ops/claims/engine.py` | `skills/agent-claim/scripts/claim.py` | `tests/compatibility/test_claim_cli.py` |
| `src/mcp_agent_ops/technology_detection/engine.py` | `skills/detect-technology-skills/scripts/detect.py` | `tests/unit/technology_detection/test_detection.py` |
| `src/mcp_agent_ops/skill_validation/engine.py` | `scripts/validate-agent-skills.py` | `tests/unit/skill_validation/test_validation.py` |

The claim engine retains its accepted command behavior and adds a context-local structured dispatch boundary used by MCP without standard-output capture. Its registry locking uses a cross-platform domain helper rather than the source script's direct POSIX `fcntl` calls; updates lock the registry itself and preserve its file identity so Windows and POSIX processes share the same disk-authoritative contract. Every checkout resolves that registry and its journal beneath the primary worktree's `.codex/agent-claim` directory. Empty legacy state migrates recoverably on the first mutation, while live legacy claims permit only exact release and contradictory state returns the same structured stop through CLI and MCP. Project-files, backlog, and all-files scope behavior is copied from the source authority, including domain-aware dirty baselines and release diagnostics, primary-only backlog and all-files ownership, and canonical sparse isolated worktrees. The direct CLI output and exit codes remain covered by the copied compatibility suite. The technology detector retains its selection behavior while accepting a trusted parsed registry snapshot, reusing manifest evidence within each scope, and blocking nested project-root symlink escapes. The skill validator accepts an optional configured-root boundary so its MCP adapter can reject nested manifest and metadata escapes while the direct compatibility surface remains available. The copied claim tests invoke the installed module rather than the former source-tree script path.

The methodology integration keeps the existing scripts as portability fallbacks while making this service the preferred deterministic operations layer. Future behavioral changes must either remain compatible with both surfaces or explicitly update their ownership and compatibility contract.
