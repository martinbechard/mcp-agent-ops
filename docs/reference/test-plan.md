# Test Plan

## Unit tests

- YAML duplicate-key, syntax, selection, and path-boundary behavior.
- Markdown local-link resolution, anchors, missing targets, ignored remote schemes, and malformed links.
- Skill-root precedence, metadata parsing, digest/content pairing, hidden install roots, resource listing, shadowing, symlink escape, explicit-refresh visibility, batch ordering, batch rejection, and traversal rejection.
- Technology registry reuse and one manifest-evidence computation per scope.
- Nested source, owner-manifest, owner-evidence, skill-manifest, and adapter-metadata symlink escape rejection, including explicitly allowed secondary skill roots and safe in-project links.
- Markdown target caching within one verification operation.

## Claim compatibility tests

- Primary, isolated, wait, recovery, extension, heartbeat, and release outcomes.
- Exact-file, tree, all-files, and exclusive-resource overlap semantics.
- Stable process exit codes and structured JSON output.
- Journal warning behavior, two-day hot retention, lossless archival, and contention reporting.
- Structured in-process dispatch with byte-compatible CLI output.
- Concurrent calls against unrelated repositories without process-global serialization.

## Contract tests

- Published MCP tool names and path-free input/output schemas, including batch loading and explicit refresh.
- In-memory calls for each capability group and immutable catalog reuse across repeated calls.
- Rejection of repository, worktree, verification, validation, and detection paths outside configured roots.
- Path-free catalog errors plus path-free skill-validation and technology-detection results.
- Skill catalog and skill-content MCP resources.

## Integration tests

- Simultaneous claim processes cannot both acquire primary ownership.
- Overlapping concurrent claims produce one safe owner and one wait outcome.
- A real stdio subprocess initializes, lists tools and resources, preserves a catalog snapshot until explicit refresh, and shuts down cleanly.

## Release gates

```text
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```
