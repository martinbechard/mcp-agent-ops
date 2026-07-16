# Copied Script Provenance

The first release deliberately copies accepted scripts from `dev-methodology` so the MCP project can expose simpler model-facing calls without reimplementing proven behavior.

Source checkout at extraction: `/Users/martinbechard/dev/dev-methodology`, commit `7074b26` with two local commits ahead of its configured upstream.

| New project file | Source file | Compatibility evidence |
|---|---|---|
| `src/mcp_agent_ops/claims/engine.py` | `skills/agent-claim/scripts/claim.py` | `tests/compatibility/test_claim_cli.py` |
| `src/mcp_agent_ops/technology_detection/engine.py` | `skills/detect-technology-skills/scripts/detect.py` | `tests/unit/technology_detection/test_detection.py` |
| `src/mcp_agent_ops/skill_validation/engine.py` | `scripts/validate-agent-skills.py` | `tests/unit/skill_validation/test_validation.py` |

The claim engine retains its accepted command behavior and adds a context-local structured dispatch boundary used by MCP without standard-output capture. The direct CLI output and exit codes remain covered by the copied compatibility suite. The technology detector retains its selection behavior while accepting a trusted parsed registry snapshot, reusing manifest evidence within each scope, and blocking nested project-root symlink escapes. The skill validator accepts an optional configured-root boundary so its MCP adapter can reject nested manifest and metadata escapes while the direct compatibility surface remains available. The copied claim tests invoke the installed module rather than the former source-tree script path.

The methodology integration keeps the existing scripts as portability fallbacks while making this service the preferred deterministic operations layer. Future behavioral changes must either remain compatible with both surfaces or explicitly update their ownership and compatibility contract.
