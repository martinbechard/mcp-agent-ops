# Core Functional Capabilities

## Claims

- The service exposes structured operations for claim status, acquisition, extension, deadline extension, heartbeat, release, reset, journal maintenance, and contention reporting.
- MCP and CLI claim operations preserve the stable outcomes and exit-code semantics of the existing `agent-claim` command.
- Claims from primary and linked worktrees coordinate through one registry beneath the primary worktree's ignored `.codex/agent-claim` directory.
- Read-only status and reporting do not create absent state. Empty legacy state migrates recoverably on the first mutation; live or contradictory legacy state produces a structured non-mutating stop except for exact live-claim release.
- Work-item claims contend by exact provider ID, preserve `work_item_id` and `activity`, and require a terminal release disposition.
- Named resource claims require configured timing evidence, calculate deadline status, and support evidenced hard-stop extension within policy.
- Claim mutations append diagnostic events; release rolls back its registry removal if its required release event cannot be persisted.
- Claims distinguish project-files, backlog, and all-files ownership. Project-files excludes backlog; backlog and all-files are primary-worktree-only.
- Explicit paths derive one file domain. Mixed project/backlog paths and cross-domain extension fail atomically with structured guidance.
- Eligible isolated project claims use the canonical ignored `.worktrees/<claim-id>` checkout and omit backlog through worktree-specific sparse checkout.
- Release removes only the exact named claim without inspecting Git or delivery state. Reports reconstruct versioned work-item activity and retain legacy-history diagnostics.

## Verification

- The service validates YAML syntax while detecting duplicate mapping keys.
- The service verifies local Markdown links without following remote URLs.
- Results identify every checked file and return structured diagnostics suitable for agent decisions.
- Verification never mutates the inspected repository.

## Reference Data

- The service loads only allowlisted direct UTF-8 reference filenames.
- An authorized working-project match precedes matches from configured user roots.
- Every matching scope contributes to one newline-separated aggregation; later matches do not shadow earlier matches.
- Reference discovery does not search subdirectories.
- A caller can load several aggregated references in one ordered, bounded, all-or-nothing operation.
- Model-facing reference results contain content, source counts, byte counts, and digests without host filesystem paths.
- An explicit refresh builds a replacement reference snapshot and publishes it atomically.

## Skill Catalog

- The service overlays recursively nested skills from conventional working-directory project roots ahead of skills from configured user roots.
- Catalog entries include stable names, descriptions, paths, content digests, and available supporting resources.
- Manifest content and its digest remain paired in one immutable process-local snapshot.
- A caller can load several complete skills or supporting resources in one ordered, bounded, all-or-nothing operation.
- A caller can optionally append `<base-name>.extension` to each loaded base skill.
- Base skills and their extensions resolve independently through the same project-before-user precedence.
- A missing optional extension does not prevent the base skill from loading.
- All model-facing catalog and skill-document results omit host filesystem paths.
- An explicit refresh builds a replacement snapshot and publishes it atomically.
- Duplicate skill names resolve by project-before-user root precedence and remain visible as shadowed entries; duplicate names within one recursive project root are rejected as ambiguous.
- Resolved resource paths must be relative, published in the active snapshot, and unable to escape the owning skill directory.

## Skill Validation and Detection

- The service validates exact skill manifests, skill directories, and configured skill roots.
- Validation rejects nested manifests and adapter metadata that resolve outside configured skill roots.
- The service detects technology skills from a trusted configured registry and the complete active skill catalog.
- Detection blocks a scope when a nested source, owner manifest, or owner-evidence path resolves outside its project root.
- Detection parses the registry once per server process and computes manifest evidence once per requested scope.

## Protocol

- The service starts over stdio without writing non-protocol output to standard output.
- A non-starting command reports package version and a location-independent digest of installed runtime resources.
- Tool results are structured and schema-described.
- Reference content is available through a bounded MCP tool.
- Skill content is available as MCP resources and through tool fallbacks for tool-only hosts.
- Claim results are produced through a structured in-process dispatcher while preserving the direct CLI contract.
- An explicitly configured evaluation audit records digest-only tool lifecycle evidence without retaining arguments or results.
