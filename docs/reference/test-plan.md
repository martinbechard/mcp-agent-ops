# Test Plan

## Unit tests

- YAML duplicate-key, syntax, selection, and path-boundary behavior.
- Markdown local-link resolution, anchors, missing targets, ignored remote schemes, and malformed links.
- Project-first reference aggregation, ordered user folders, recursive relative-path discovery, duplicate resolved-file suppression, UTF-8 decoding, immutable content and digest pairing, batch rejection, size limits, traversal rejection, and symlink escape.
- Working-directory project overlays, recursive nested project discovery, skill-root precedence,
  independent extension precedence, optional extension composition, aggregate digests, extension
  naming validation, extension-aware size limits, name-to-path lookup, same-root ambiguity
  rejection, metadata parsing, hidden install roots, resource listing, shadowing, symlink escape,
  explicit-refresh visibility, batch ordering, batch rejection, and traversal rejection.
- Technology registry reuse and one manifest-evidence computation per scope.
- Nested source, owner-manifest, owner-evidence, skill-manifest, and adapter-metadata symlink escape rejection, including explicitly allowed secondary skill roots and safe in-project links.
- Markdown target caching within one verification operation.
- Hierarchical mapping and sequence rendering, HTML escaping, JSON/YAML content and file input,
  copy-safe text spacing, complete payload copying, compact accessible SVG action controls,
  level-first control order, plus/minus global controls, progressive level visibility, dotted
  one-based numbering, transparent singleton roots, exact completed-item paths, optional read-only
  completion markers, durable plan creation, JSON source-path returns, unique-title and exact-path
  targeting, completion and text updates, branch-subtree completion, upward completion cascading,
  ancestor reopening after completion and structural mutation, depth-first next-leaf selection
  with parent context, child replacement and insertion, peer insertion, regeneration, packaged
  and caller-supplied themes, cyclic input rejection, and self-contained output-file writing.

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
- Primary and linked-worktree canonical state resolution, absent-state read-only behavior, exact layout-version-two markers, locked-descriptor migration validation without pathname reopening, empty legacy-history migration, interrupted recovery, exact live-claim drain, concurrent release-to-marker handoff, platform-aware locked-file identity, first-lock mutating and read-only stale-inode rejection in threads and real processes, bounded operation-lock exhaustion, split-state refusal, and ignored operational scope.

## Contract tests

- Stable non-starting command-line package version and installed-runtime identity.
- Fail-closed startup when an evaluator-pinned installed-runtime digest does not match.
- Published MCP tool names and bounded input/output schemas, including work-item fields, resource
  timing, deadline extension, release disposition, reset, all three broad claim domains, aggregated
  reference loading, precedence-resolved skill path lookup, optional extension switches,
  validation by name or absolute path, batch loading, explicit refresh, hierarchy rendering, and
  durable hierarchy-plan creation and structured mutation results.
- In-memory calls for each capability group and immutable catalog reuse across repeated calls.
- CLI and MCP parity for the canonical registry path and structured migration stops.
- Rejection of repository, worktree, verification, validation, detection, hierarchy, and persisted
  hierarchy-theme paths outside configured roots.
- Actionable skill-catalog configuration errors that identify invalid manifests, resolved symlink
  targets, configured roots, and exact root-setting repairs; path-free reference errors plus
  path-free skill-validation and technology-detection results.
- Digest-only tool audit lifecycle, exclusive audit-root confinement, safe shared parent and subagent streams, content omission, and real stdio evidence.
- Skill catalog and skill-content MCP resources.

## Integration tests

- The checked-in hierarchy gallery generator produces its index and all interactive example pages
  from YAML filename, full JSON content, and in-memory inputs. The delivery-plan example also
  produces its durable JSON source. The gallery includes a caller-supplied theme and
  presentation-only parameter callouts.
- Simultaneous claim processes cannot both acquire primary ownership.
- Overlapping concurrent claims produce one safe owner and one wait outcome.
- A real stdio subprocess initializes, advertises current work-item, deadline, release, reset,
  broad-domain, and hierarchy tools, invokes all three hierarchy operations, preserves reference
  and skill snapshots until explicit refresh, returns the next executable plan task, and shuts down
  cleanly.
- Windows CI runs the complete claim compatibility suite plus a real stdio subprocess; evaluator-only shared audit remains on its documented POSIX boundary.

## Release gates

```text
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```
