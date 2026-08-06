# Test Plan

## Unit tests

- YAML duplicate-key, syntax, selection, and path-boundary behavior.
- Markdown local-link resolution, anchors, missing targets, ignored remote schemes, and malformed links.
- Working-directory project overlays, recursive nested project discovery, skill-root precedence, name-to-path lookup, same-root ambiguity rejection, metadata parsing, digest/content pairing, hidden install roots, resource listing, shadowing, symlink escape, explicit-refresh visibility, batch ordering, batch rejection, and traversal rejection.
- Technology registry reuse and one manifest-evidence computation per scope.
- Nested source, owner-manifest, owner-evidence, skill-manifest, and adapter-metadata symlink escape rejection, including explicitly allowed secondary skill roots and safe in-project links.
- Markdown target caching within one verification operation.

## Claim compatibility tests

- Work-item, path, resource, wait, extension, deadline-extension, heartbeat, release, and reset outcomes.
- Exact-file, tree, project-files, backlog, all-files, and exclusive-resource overlap semantics.
- Broad-domain mutual exclusion, explicit backlog compatibility normalization, and atomic mixed-domain rejection.
- Primary-only backlog and all-files routing plus canonical project isolation without a backlog checkout.
- Exact release without Git or delivery inspection, including work-item disposition validation and registry rollback on journal failure.
- Stable process exit codes and structured JSON output.
- Journal warning behavior, two-day hot retention, lossless archival, and contention reporting.
- Structured in-process dispatch with byte-compatible CLI output.
- Concurrent calls against unrelated repositories without process-global serialization.
- Primary and linked-worktree canonical state resolution, absent-state read-only behavior, exact layout-version-two markers, empty legacy-history migration, interrupted recovery, exact live-claim drain, concurrent release-to-marker handoff, platform-aware locked-file identity, first-lock mutating and read-only stale-inode rejection in threads and real processes, bounded operation-lock exhaustion, split-state refusal, and ignored operational scope.

## Contract tests

- Stable non-starting command-line package version and installed-runtime identity.
- Fail-closed startup when an evaluator-pinned installed-runtime digest does not match.
- Published MCP tool names and bounded input/output schemas, including work-item fields, resource timing, deadline extension, release disposition, reset, all three broad claim domains, precedence-resolved skill path lookup, validation by name or absolute path, batch loading, and explicit refresh.
- In-memory calls for each capability group and immutable catalog reuse across repeated calls.
- CLI and MCP parity for the canonical registry path and structured migration stops.
- Rejection of repository, worktree, verification, validation, and detection paths outside configured roots.
- Path-free catalog errors plus path-free skill-validation and technology-detection results.
- Digest-only tool audit lifecycle, exclusive audit-root confinement, safe shared parent and subagent streams, content omission, and real stdio evidence.
- Skill catalog and skill-content MCP resources.

## Integration tests

- Simultaneous claim processes cannot both acquire primary ownership.
- Overlapping concurrent claims produce one safe owner and one wait outcome.
- A real stdio subprocess initializes, advertises current work-item, deadline, release, reset, and broad-domain schemas, lists tools and resources, preserves a catalog snapshot until explicit refresh, and shuts down cleanly.
- Windows CI runs the complete claim compatibility suite plus a real stdio subprocess; evaluator-only shared audit remains on its documented POSIX boundary.

## Release gates

```text
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```
