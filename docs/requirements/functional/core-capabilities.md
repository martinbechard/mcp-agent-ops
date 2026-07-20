# Core Functional Capabilities

## Claims

- The service exposes structured operations for claim status, acquisition, extension, heartbeat, release, journal maintenance, and contention reporting.
- MCP and CLI claim operations preserve the stable outcomes and exit-code semantics of the existing `agent-claim` command.
- Claims from linked worktrees coordinate through one registry in the Git common directory.
- Claim mutations append diagnostic events without making journal availability part of ownership safety.
- Claims distinguish project-files, backlog, and all-files ownership. Project-files excludes backlog; backlog and all-files are primary-worktree-only.
- Explicit paths derive one file domain. Mixed project/backlog paths and cross-domain extension fail atomically with structured guidance.
- Eligible isolated project claims use the canonical ignored `.worktrees/<claim-id>` checkout and omit backlog through worktree-specific sparse checkout.
- Recovery and release evaluate owned-domain status while preserving unchanged out-of-domain dirtiness; later out-of-domain status or commit changes reject release with exact path diagnostics.

## Verification

- The service validates YAML syntax while detecting duplicate mapping keys.
- The service verifies local Markdown links without following remote URLs.
- Results identify every checked file and return structured diagnostics suitable for agent decisions.
- Verification never mutates the inspected repository.

## Skill Catalog

- The service overlays recursively nested skills from conventional working-directory project roots ahead of skills from configured user roots.
- Catalog entries include stable names, descriptions, paths, content digests, and available supporting resources.
- Manifest content and its digest remain paired in one immutable process-local snapshot.
- A caller can load several complete skills or supporting resources in one ordered, bounded, all-or-nothing operation.
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
- Skill content is available as MCP resources and through tool fallbacks for tool-only hosts.
- Claim results are produced through a structured in-process dispatcher while preserving the direct CLI contract.
- An explicitly configured evaluation audit records digest-only tool lifecycle evidence without retaining arguments or results.
