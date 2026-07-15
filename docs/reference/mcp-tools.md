# MCP Tool Reference

The server intentionally publishes small named operations so an LLM supplies data rather than generating Python or shell commands.

## Claims

| Tool | Required arguments | Purpose |
|---|---|---|
| `claim_status` | `repository` | Read the authoritative live registry. |
| `claim_acquire` | `repository`, `claim_id`, `agent`, `task`, `root_task_id` | Acquire exact files, trees, all files, or exclusive resources atomically. |
| `claim_extend` | `repository`, `claim_id` | Add newly discovered scope atomically. |
| `claim_heartbeat` | `repository`, `claim_id` | Refresh an active heartbeat. |
| `claim_release` | `repository`, `claim_id` | Release a clean committed or explicit no-change claim. |
| `claim_maintain_journal` | `repository` | Retain the hot UTC window and archive older complete days. |
| `claim_report` | `repository` | Return structured contention and lifecycle metrics. |

Claim results contain `exit_code` and the copied engine's structured `result`. The result outcome remains authoritative: successful calls can have different outcomes, and unsuccessful ownership attempts such as `WAIT` are valid structured results rather than protocol failures.

Example acquisition arguments:

```json
{
  "repository": "/workspace/project",
  "claim_id": "task-123",
  "agent": "implementation-agent",
  "task": "task-123",
  "root_task_id": "task-123",
  "files": ["src/feature.py", "tests/test_feature.py"]
}
```

## Verification

| Tool | Required arguments | Purpose |
|---|---|---|
| `verify_yaml` | `repository_root`, `paths` | Detect syntax errors, duplicate keys, missing files, decoding failures, and root escape. |
| `verify_markdown_links` | `repository_root` | Check local targets and heading anchors; `patterns` defaults to every Markdown file. |

Verification results contain `ok`, `checked_files`, and structured `findings`. They never mutate the inspected repository or use the network.

## Skills

| Tool | Required arguments | Purpose |
|---|---|---|
| `skill_list` | none | Return resolved names, descriptions, digests, resources, and shadowed definitions. |
| `skill_read` | `name` | Return one complete `SKILL.md`. |
| `skill_read_resource` | `name`, `resource_path` | Read one safe supporting resource. |
| `skill_validate` | `paths` | Run the copied Agent Skill validator. |
| `detect_technology_skills` | `project_root`, `scopes` | Run copied evidence-based technology detection using server configuration. |

Skill roots come from `MCP_AGENT_OPS_SKILL_ROOTS`. Technology detection additionally requires `MCP_AGENT_OPS_DETECTION_REGISTRY`.

## Resources

| URI | Content |
|---|---|
| `skill://catalog` | Current structured catalog JSON. |
| `skill://{name}` | Complete selected skill document. |
| `skill-resource://{name}/{resource_path}` | Selected supporting text or binary resource. |

Tool fallbacks remain available because some MCP hosts do not expose resources directly to their agents.
