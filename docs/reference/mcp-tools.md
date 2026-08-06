# MCP Tool Reference

The server intentionally publishes small named operations so an LLM supplies data rather than generating Python or shell commands.

## Claims

| Tool | Required arguments | Purpose |
|---|---|---|
| `claim_status` | `repository` | Read the authoritative live registry. |
| `claim_acquire` | `repository`, `claim_id`, `agent`, `task`, `root_task_id` | Acquire one project-files, backlog, all-files, explicit-path domain, plus optional resources. |
| `claim_extend` | `repository`, `claim_id` | Add newly discovered same-domain scope atomically. |
| `claim_heartbeat` | `repository`, `claim_id` | Refresh an active heartbeat. |
| `claim_release` | `repository`, `claim_id` | Release a clean committed or explicit no-change claim. |
| `claim_maintain_journal` | `repository` | Retain the hot UTC window and archive older complete days. |
| `claim_report` | `repository` | Return structured contention and lifecycle metrics. |

Claim results contain `exit_code` and the copied engine's structured `result`. This source checkout advertises result schema version 2 through the claim tool descriptions. The result outcome is authoritative and includes `legacy_outcome` only when the canonical name replaces a prior result name. Every checkout resolves the reported registry path beneath the primary worktree's `.codex/agent-claim` directory. Read-only status and reporting keep absent state write-free. Successful calls can have different outcomes, and unsuccessful ownership attempts such as `CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED` are valid structured results rather than protocol failures. Clients must capability-gate schema version 2 rather than infer it from a package version; published release 0.4.0 predates this contract.

| Canonical outcome | Meaning and next action | Legacy outcome | Exit code |
|---|---|---|---|
| `SHARED_CHECKOUT_ACQUIRED` | Ownership was acquired in the repository's existing shared checkout; work only within the acquired scope there. | `PRIMARY` | 0 |
| `ISOLATED_CHECKOUT_ACQUIRED` | Ownership was acquired in a prepared isolated checkout; work in the returned checkout. | `ISOLATE` | 0 |
| `DIRTY_CHECKOUT_RECOVERY_ACQUIRED` | Recovery ownership was acquired over authorized dirty state; checkpoint it before cleanup. | `RECOVER` | 0 |
| `CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED` | No ownership was acquired because scope overlaps another owner; await a handoff or choose non-overlapping scope. | `WAIT` | 3 |
| `SHARED_CHECKOUT_REQUIRED` | No ownership was acquired because the operation must run from the shared checkout; hand it there. | `PRIMARY_REQUIRED` | 3 |
| `SHARED_CHECKOUT_RELEASE_REQUIRED` | No ownership was acquired because another claim owns the shared checkout; await release notification. | `PRIMARY_REQUIRED` | 3 |
| `ISOLATED_CHECKOUT_SETUP_REQUIRED` | No ownership was acquired because isolation arguments are required; prepare the returned target. | `ISOLATE_REQUIRED` | 4 |
| `DIRTY_CHECKOUT_RECOVERY_AUTHORIZATION_REQUIRED` | No ownership was acquired because dirty state needs explicit recovery authority. | `RECOVERY_REQUIRED` | 5 |
| `CLAIM_STATE_MIGRATION_BLOCKED` | Canonical state cannot be selected safely; drain the exact live legacy claim or reconcile the reported migration boundary before retrying with the same helper. | None | 3 |

Unlisted explicit outcomes keep their existing names and omit `legacy_outcome`. Schema-version-1 journal events remain append-only with their original outcome strings. New `PRIMARY_REQUIRED` events record explicit `shared_checkout_claimed` context. Reports use that context to distinguish the two canonical meanings, publish canonical `outcome_counts`, and retain original strings in `raw_outcome_counts`. Historical events without the field remain raw `PRIMARY_REQUIRED` and appear in `outcome_normalization_gaps`; active claim counts are not treated as proof of shared-checkout ownership.

The broad file selectors are mutually exclusive:

- `project_files` owns the repository file tree except `backlog` and ignored operational worktree state. It requires `scope_reason` and may use a canonical `.worktrees/<claim-id>` checkout when another independent project claim is active.
- `backlog` owns the complete backlog subtree and is primary-worktree-only.
- `all_files` explicitly owns both domains, requires `scope_reason`, and is primary-worktree-only.

Explicit backlog files and trees remain compatible inputs and are reported with `compat_backlog_path`. A request mixing project and backlog paths returns `INVALID_SCOPE` with reason `mixed_file_domains`. Backlog or all-files acquisition while the shared checkout is occupied returns `SHARED_CHECKOUT_RELEASE_REQUIRED`; the same request from another checkout when the shared checkout is available, including backlog-domain extension from an isolated claim, returns `SHARED_CHECKOUT_REQUIRED`. Both retain exit code 3 and leave the registry unchanged. Release rejects post-acquisition out-of-domain worktree changes as `out_of_domain_changes` and out-of-domain committed paths as `out_of_domain_commit`.

The first mutating operation migrates only an empty legacy Git-common-directory registry and preserves usable history. A live legacy registry permits exact release only. Contradictory dual state, incomplete recovery, or replaced legacy markers return `CLAIM_STATE_MIGRATION_BLOCKED` without mutation or helper fallback.

Repository and worktree paths must be absolute and resolve beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS`.

Example acquisition arguments:

```json
{
  "repository": "/workspace/project",
  "claim_id": "task-123",
  "agent": "implementation-agent",
  "task": "task-123",
  "root_task_id": "task-123",
  "project_files": true,
  "scope_reason": "project implementation"
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
| `skill_find` | `name` | Return the precedence-resolved absolute `SKILL.md` path for one catalog skill. |
| `skill_read` | `name` | Return one complete path-free `SKILL.md` result. |
| `skill_read_resource` | `name`, `resource_path` | Read one safe supporting resource. |
| `skill_load` | `names` | Load one to thirty-two complete skills in requested order with no host paths in the result. |
| `skill_resource_load` | `requests` | Load one to sixty-four supporting resources in requested order. |
| `skill_refresh` | none | Build and atomically publish a new process-local skill catalog snapshot. |
| `skill_validate` | `paths` | Validate catalog skill names or explicit absolute paths within configured skill roots or the authorized working project. |
| `detect_technology_skills` | `project_root`, `scopes` | Run copied evidence-based technology detection using server configuration. |

Except for the explicit `skill_find` result, model-facing catalog and skill-document results omit configured roots, manifest paths, and shadowed paths. `skill_load` and `skill_resource_load` are bounded, all-or-nothing operations: invalid, duplicate, missing, unsafe, or oversized requests return an error-only result rather than partial content. Every batch result includes `catalog_revision`; each loaded skill or resource also carries its own SHA-256 digest. A resource must be listed in the active catalog snapshot, so newly added resources require `skill_refresh`. Resource contents are read on demand and their returned digest identifies the exact bytes.

Skill roots come from `MCP_AGENT_OPS_SKILL_ROOTS`. Name-based validation uses the same precedence-resolved catalog as skill loading. An explicit absolute validation path may additionally resolve beneath the server's working project when that project is itself beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS`. Every discovered manifest or metadata file must remain beneath the selected validation boundary. Technology detection additionally requires `MCP_AGENT_OPS_DETECTION_REGISTRY`; its project path and every discovered source, owner manifest, and owner-evidence file must remain beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS`. Model-facing validation and detection results use relative identities rather than configured host paths. The parsed technology registry remains fixed until server restart.

## Resources

| URI | Content |
|---|---|
| `skill://catalog` | Active structured catalog snapshot as JSON. |
| `skill://{name}` | Complete selected skill document from the active snapshot. |
| `skill-resource://{name}/{resource_path}` | Selected supporting text or binary resource. |

Tool fallbacks remain available because some MCP hosts do not expose resources directly to their agents.

## Evaluation Audit

`MCP_AGENT_OPS_AUDIT_LOG` enables one evaluator-owned JSON Lines tool lifecycle trace when `MCP_AGENT_OPS_AUDIT_ROOTS` also contains its destination. The default exclusive mode requires a new file and preserves the version-one record contract. `MCP_AGENT_OPS_AUDIT_SHARED=true` plus a 32-character lowercase hexadecimal `MCP_AGENT_OPS_AUDIT_SESSION_ID` permits inherited parent and subagent server processes to open the same owner-only file; version-two records carry that session identity, a random stream identity, and a process-local sequence, and writes are serialized with a POSIX file lock. Both modes contain only canonical tool name, call identity, sequence, status, and SHA-256 digests. Shared version-two terminal records also contain a bounded canonical outcome when the operation exposes one. The audit is not an MCP tool, is invisible to the model, and never stores arguments or returned content.

Successful `skill_load` and `skill_resource_load` calls report `LOADED`; structured batch rejections report `REJECTED`. These outcomes disclose no skill names, resource paths, rejection codes, messages, or loaded content.
