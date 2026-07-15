# Copied Script Provenance

The first release deliberately copies accepted scripts from `dev-methodology` so the MCP project can expose simpler model-facing calls without reimplementing proven behavior.

Source checkout at extraction: `/Users/martinbechard/dev/dev-methodology`, commit `7074b26` with two local commits ahead of its configured upstream.

| New project file | Source file | Compatibility evidence |
|---|---|---|
| `src/mcp_agent_ops/claims/engine.py` | `skills/agent-claim/scripts/claim.py` | `tests/compatibility/test_claim_cli.py` |
| `src/mcp_agent_ops/technology_detection/engine.py` | `skills/detect-technology-skills/scripts/detect.py` | `tests/unit/technology_detection/test_detection.py` |
| `src/mcp_agent_ops/skill_validation/engine.py` | `scripts/validate-agent-skills.py` | `tests/unit/skill_validation/test_validation.py` |

The claim and technology-detection implementations retain their behavior verbatim apart from project-local code headers. The skill validator adds documentation comments without changing validation control flow. The copied claim tests invoke the installed module rather than the former source-tree script path.

Future changes should either be applied to both owners with compatibility evidence or intentionally make this upstream project canonical during the separate `dev-methodology` retrofit.
