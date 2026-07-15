# Test Plan

## Unit tests

- YAML duplicate-key, syntax, selection, and path-boundary behavior.
- Markdown local-link resolution, anchors, missing targets, ignored remote schemes, and malformed links.
- Skill-root precedence, metadata parsing, digests, resource listing, shadowing, and traversal rejection.

## Claim compatibility tests

- Primary, isolated, wait, recovery, extension, heartbeat, and release outcomes.
- Exact-file, tree, all-files, and exclusive-resource overlap semantics.
- Stable process exit codes and structured JSON output.
- Journal warning behavior, two-day hot retention, lossless archival, and contention reporting.

## Contract tests

- Published MCP tool names and input/output schemas.
- In-memory calls for each capability group.
- Skill catalog and skill-content MCP resources.

## Integration tests

- Simultaneous claim processes cannot both acquire primary ownership.
- Overlapping concurrent claims produce one safe owner and one wait outcome.
- A real stdio subprocess initializes, lists tools and resources, invokes representative operations, and shuts down cleanly.

## Release gates

```text
uv run pytest
uv run ruff check .
uv run mypy src
git diff --check
```
