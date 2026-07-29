# High-Level Architecture

The project uses a domain-and-adapter structure.

```text
MCP host -> FastMCP adapter -> domain service -> Git repository / skill roots
CLI user -> CLI adapter -----^
```

## Domain ownership

- `claims` owns registry locking, scope overlap, worktree selection, lifecycle events, journal maintenance, and reporting.
- `verification` owns deterministic YAML and Markdown checks.
- `skill_catalog` owns root precedence, metadata extraction, immutable manifest snapshots, batch limits, digests, and safe content retrieval.
- `skill_validation` owns deterministic Agent Skill structure validation.
- `technology_detection` owns evidence-based skill selection from a trusted parsed registry.

No domain module depends on FastMCP. Adapters translate typed requests to domain calls and translate domain results to stable structured responses.

## Claim compatibility

The CLI adapter preserves the accepted `claim.py` registry, journal, output, and exit-code contracts as an operational fallback and black-box compatibility surface. MCP tools use a structured in-process dispatcher rather than capturing standard output. A cross-platform exclusive OS lock is applied directly to the repository-global registry, whose file identity is preserved by in-place updates. This disk lock remains the cross-process ownership authority on POSIX and Windows, while unrelated repositories can proceed concurrently inside one MCP server.

Every claim records one file domain: project-files, backlog, all-files, or none for resource-only coordination. Exact paths are classified into project or backlog ownership. The claims domain rejects mixed ownership before registry mutation, routes backlog and all-files to the primary worktree, and creates eligible project isolation only at the canonical ignored worktree root with backlog excluded. Resource-only claims serialize only exact resource overlaps, do not occupy a file or shared-checkout lane, and ignore unrelated worktree dirtiness during release. Domain-aware baseline evidence lets release distinguish owned work from unchanged outside dirtiness and reject later outside changes without staging, reverting, or cleaning them. The MCP and CLI adapters only translate these engine outcomes.

## Verification boundary

Verification operations are deliberately composable rather than embedding `dev-methodology` policy. The later methodology retrofit can call these primitives and continue to own methodology-specific profiles and expectations.

## Skill-loading boundary

The server provides path-free catalog listing and content retrieval, but it does not claim that a model has retained a skill. The explicit `skill_find` operation returns the precedence-selected manifest path so callers can pass it to filesystem-oriented operations such as `skill_validate`. Each agent harness owns context insertion and per-task load receipts. The server reports immutable manifest content and digests so a harness can bind evidence to exact bytes.

One catalog snapshot is built lazily per server process. When the process working directory resolves beneath an allowed workspace, the adapter prepends recursive `<cwd>/.agents/skills` and `<cwd>/.codex/skills` project roots to the configured user roots. This gives project definitions precedence without moving project-context rules into the catalog domain. Ordinary list and load operations reuse the snapshot, eliminating repeated tree scans. `skill_refresh` builds a complete replacement outside the publication lock and then swaps it atomically, so readers observe either the old or new revision. Resource paths are part of the catalog revision; resource bytes remain progressively loaded and carry an independent digest.

The technology registry is parsed once per server process. A detection call computes owner evidence and manifest dependencies once per requested scope, then evaluates all configured skill predicates against that shared evidence.

## Filesystem boundaries

The host configures separate user skill roots and workspace roots. Automatic project skill roots are accepted only when the process working directory is beneath an allowed workspace, and their conventional paths must remain beneath that project after symlink resolution. Model-supplied repository, project, verification, validation, and worktree paths are resolved only beneath those boundaries after symlink resolution. Skill validation and technology detection repeat containment at each nested read boundary, so a safe top-level directory cannot delegate access through an escaping manifest, metadata, source, or owner-evidence symlink. Model-facing catalog, validation, and detection results omit configured host paths; `skill_find` is the narrow operation that intentionally returns one selected manifest path. The boundary is reproducibility and host-state protection for ordinary agent work; it is not a general hostile-code sandbox.

## Transport

The transport is stdio. Process memory is used only for immutable read snapshots; disk remains authoritative and separate server processes continue coordinating claim mutations through repository-global state. An HTTP transport can be added later without changing domain interfaces.

The non-starting identity command reports the package version plus a location-independent digest over installed runtime resources. Evaluators bind that digest together with the launcher digest and server configuration before execution.

An optional evaluation-only middleware writes a separate digest-only tool lifecycle stream beneath an administrator-configured audit root. Exclusive mode owns one file for one server process. Explicit shared mode lets inherited parent and subagent MCP processes append separate random stream identities under a POSIX file lock without sharing call identifiers or process-local sequences. It records a started event before dispatch and a terminal digest after dispatch. A post-dispatch audit write failure never converts a completed mutation into a retryable tool failure; the evaluator instead rejects the incomplete audit stream.
