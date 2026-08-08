# MCP Tool Reference

The server intentionally publishes small named operations so an LLM supplies data rather than generating Python or shell commands.

## Claims

| Tool | Required arguments | Purpose |
|---|---|---|
| `claim_status` | `repository` | Read the authoritative live registry. |
| `claim_acquire` | `repository`, `claim_id`, `agent`, `task`, `root_task_id` | Acquire one work-item activity, file domain, or policy-bounded resource. |
| `claim_extend` | `repository`, `claim_id` | Add newly discovered path or timed-resource scope atomically. |
| `claim_extend_deadline` | `repository`, `claim_id`, `requested_hard_stop_duration_seconds`, `extension_evidence` | Extend one resource hard stop within configured policy. |
| `claim_heartbeat` | `repository`, `claim_id` | Refresh an active heartbeat. |
| `claim_release` | `repository`, `claim_id` | Release one exact claim; work-item claims also require `disposition`. |
| `claim_reset` | `repository` | Replace the live registry with an empty claim list under its lock. |
| `claim_maintain_journal` | `repository` | Retain the hot UTC window and archive older complete days. |
| `claim_report` | `repository` | Return structured contention and lifecycle metrics. |

Claim results contain `exit_code` and the copied engine's structured `result`. Result schema version 2 is authoritative and includes `legacy_outcome` only when the canonical name replaces a prior result name. Every checkout resolves the reported registry path beneath the primary worktree's `.codex/agent-claim` directory. Read-only status and reporting keep absent state write-free. Unsuccessful ownership attempts such as `CLAIM_SCOPE_CONFLICT_WAIT_REQUIRED` are valid structured results rather than protocol failures.

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

- `project_files` owns the repository file tree except `backlog` and ignored operational worktree state. It requires `scope_reason` and may use a caller-requested canonical `.worktrees/<claim-id>` checkout.
- `backlog` owns the complete backlog subtree and is primary-worktree-only.
- `all_files` explicitly owns both domains, requires `scope_reason`, and is primary-worktree-only.

Explicit backlog files and trees remain compatible inputs and are reported with `compat_backlog_path`. A request mixing project and backlog paths returns `INVALID_SCOPE` with reason `mixed_file_domains`. Primary-only scope requested from a linked checkout returns `SHARED_CHECKOUT_REQUIRED` and leaves the registry unchanged. Release removes only the exact named claim and does not inspect Git or delivery state.

Work-item acquisition supplies `work_item_id` with activity `work` or `update` and cannot combine that scope with file or resource ownership. Work-item release requires disposition `done`, `blocked`, or `handoff`; only `blocked` may include a bounded `blocker_reference`. Resource acquisition or extension supplies one resource plus `resource_class`, `resource_id`, `expected_duration_seconds`, and `requested_hard_stop_duration_seconds`. The project deadline policy controls the accepted maximum and cleanup grace. Reports include a schema-version-one `work_items` section with deterministic activity segments and diagnostics.

The first mutating operation migrates only an empty legacy Git-common-directory registry and preserves usable history. Canonical `state.json` contains `schema_version`, `state_layout_version: 2`, `migration_status`, and `origin`. Successful legacy migration leaves a registry directory with child `state.json` and a regular event marker file using the exact command-helper payloads. A live legacy registry permits exact release only. Contradictory dual state, incomplete migration, or replaced legacy markers return `CLAIM_STATE_MIGRATION_BLOCKED` without mutation or helper fallback.

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

## Reference Data

Reference tools return allowlisted text from the active immutable snapshot.

| Tool | Required arguments | Purpose |
|---|---|---|
| `reference_load` | `names` | Load one to thirty-two aggregated references in requested order. |
| `reference_refresh` | none | Build and atomically publish a new reference snapshot. |

`MCP_AGENT_OPS_REFERENCE_NAMES` contains the exact permitted direct filenames. `MCP_AGENT_OPS_REFERENCE_ROOTS` contains ordered user roots. Both lists use the operating-system path separator. When the working directory is beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS`, the server searches its direct file first. It then searches each configured user root without recursion.

Every matching scope contributes to the result. The server joins source contents with one newline. It deduplicates scopes that resolve to the same file. Results contain a source count, path-free scope labels, byte counts, source digests, and an aggregate digest. One reference can include at most 64 sources, and one load can return at most 1 MiB of combined reference content. Invalid, duplicate, missing, unsafe, non-text, or oversized requests return no partial content. Newly added or changed references require `reference_refresh`.

## Skills

| Tool | Arguments | Purpose |
|---|---|---|
| `skill_list` | none | Return path-free names, descriptions, digests, resources, and shadowing counts. |
| `skill_find` | `name` | Return the precedence-resolved absolute `SKILL.md` path for one catalog skill. |
| `skill_read` | `name`; optional `include_extensions` | Return one complete path-free skill, optionally with its resolved extension appended. |
| `skill_read_resource` | `name`, `resource_path` | Read one safe supporting resource. |
| `skill_load` | `names`; optional `include_extensions` | Load one to thirty-two complete skills in requested order, optionally with extensions. |
| `skill_resource_load` | `requests` | Load one to sixty-four supporting resources in requested order. |
| `skill_refresh` | none | Build and atomically publish a new process-local skill catalog snapshot. |
| `skill_validate` | `paths` | Validate catalog skill names or explicit absolute paths within configured skill roots or the authorized working project. |
| `detect_technology_skills` | `project_root`, `scopes` | Run copied evidence-based technology detection using server configuration. |

Except for the explicit `skill_find` result, model-facing catalog and skill-document results omit configured roots, manifest paths, and shadowed paths. `skill_load` and `skill_resource_load` are bounded, all-or-nothing operations: invalid, duplicate, missing, unsafe, or oversized requests return an error-only result rather than partial content. Every batch result includes `catalog_revision`; each loaded skill or resource also carries its own SHA-256 digest. A resource must be listed in the active catalog snapshot, so newly added resources require `skill_refresh`. Resource contents are read on demand and their returned digest identifies the exact bytes.

### Optional skill extensions

The `include_extensions` switch defaults to `false` on `skill_read` and `skill_load`. When the
switch is `true`, the loader searches for `<base-name>.extension` as a normal catalog skill. The
base name and extension name each use the complete project-before-user precedence order.
Independent resolution supports all combinations of project and configured user definitions.

If the extension exists, the loader appends its complete `SKILL.md` after the base document with
one newline between them. The returned `digest` identifies this combined content, and
`applied_extensions` contains the extension name. If the extension is absent, the base content and
digest stay unchanged and `applied_extensions` is empty. Appended bytes count toward the existing
one-mebibyte batch limit.

Extension skills remain ordinary catalog entries. Their names must use the
`<base-name>.extension` convention. Their supporting resources remain under the extension skill's
own name and are available through `skill_read_resource` or `skill_resource_load`. The
`skill://{name}` resource continues to return the exact named skill without optional composition.

For example, these `skill_read` arguments enable extension lookup for `python`:

```json
{
  "name": "python",
  "include_extensions": true
}
```

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

Successful `reference_load` calls report `LOADED`; structured rejections report `REJECTED`. `reference_refresh` reports `CATALOG` when at least one reference is available and `EMPTY` otherwise. These outcomes disclose no reference names, paths, rejection codes, messages, or content.
