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

Repository and worktree paths must be absolute and resolve beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS`.

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

`repository_root` must be absolute and resolve beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS`.

## Skills

| Tool | Required arguments | Purpose |
|---|---|---|
| `skill_list` | none | Return path-free names, descriptions, digests, resources, and shadowing counts. |
| `skill_read` | `name` | Return one complete path-free `SKILL.md` result. |
| `skill_read_resource` | `name`, `resource_path` | Read one safe supporting resource. |
| `skill_load` | `names` | Load one to thirty-two complete skills in requested order with no host paths in the result. |
| `skill_resource_load` | `requests` | Load one to sixty-four supporting resources in requested order. |
| `skill_refresh` | none | Build and atomically publish a new process-local skill catalog snapshot. |
| `skill_validate` | `paths` | Run the copied Agent Skill validator. |
| `detect_technology_skills` | `project_root`, `scopes` | Run copied evidence-based technology detection using server configuration. |

All model-facing catalog and skill-document results omit configured roots, manifest paths, and shadowed paths. `skill_load` and `skill_resource_load` are bounded, all-or-nothing operations: invalid, duplicate, missing, unsafe, or oversized requests return an error-only result rather than partial content. Every batch result includes `catalog_revision`; each loaded skill or resource also carries its own SHA-256 digest. A resource must be listed in the active catalog snapshot, so newly added resources require `skill_refresh`. Resource contents are read on demand and their returned digest identifies the exact bytes.

Skill roots come from `MCP_AGENT_OPS_SKILL_ROOTS`. Validation paths and every discovered manifest or metadata file must resolve beneath those roots. Technology detection additionally requires `MCP_AGENT_OPS_DETECTION_REGISTRY`; its project path and every discovered source, owner manifest, and owner-evidence file must remain beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS`. Model-facing validation and detection results use relative identities rather than configured host paths. The parsed technology registry remains fixed until server restart.

## Resources

| URI | Content |
|---|---|
| `skill://catalog` | Active structured catalog snapshot as JSON. |
| `skill://{name}` | Complete selected skill document from the active snapshot. |
| `skill-resource://{name}/{resource_path}` | Selected supporting text or binary resource. |

Tool fallbacks remain available because some MCP hosts do not expose resources directly to their agents.

## Evaluation Audit

`MCP_AGENT_OPS_AUDIT_LOG` enables one evaluator-owned JSON Lines tool lifecycle trace when `MCP_AGENT_OPS_AUDIT_ROOTS` also contains its destination. The default exclusive mode requires a new file and preserves the version-one record contract. `MCP_AGENT_OPS_AUDIT_SHARED=true` plus a 32-character lowercase hexadecimal `MCP_AGENT_OPS_AUDIT_SESSION_ID` permits inherited parent and subagent server processes to open the same owner-only file; version-two records carry that session identity, a random stream identity, and a process-local sequence, and writes are serialized with a POSIX file lock. Both modes contain only canonical tool name, call identity, sequence, status, and SHA-256 digests. Shared version-two terminal records also contain a bounded canonical outcome when the operation exposes one. The audit is not an MCP tool, is invisible to the model, and never stores arguments or returned content.
