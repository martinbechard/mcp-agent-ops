# High-Level Architecture

The project uses a domain-and-adapter structure.

```text
MCP host -> FastMCP adapter -> domain service -> Git repository / hierarchy files / reference and skill roots
CLI user -> CLI adapter -----^
```

## Domain ownership

- `claims` owns registry locking, scope overlap, worktree selection, lifecycle events, journal maintenance, and reporting.
- `verification` owns deterministic YAML and Markdown checks.
- `reference_data` owns direct-file scope aggregation, filename allowlists, immutable content snapshots, batch limits, and digests.
- `skill_catalog` owns root precedence, metadata extraction, immutable manifest snapshots, batch limits, digests, and safe content retrieval.
- `skill_validation` owns deterministic Agent Skill structure validation.
- `technology_detection` owns evidence-based skill selection from a trusted parsed registry.
- `hierarchy` owns safe parsing, self-contained themed HTML rendering, and durable plan mutation.

No domain module depends on FastMCP. Adapters translate typed requests to domain calls and translate domain results to stable structured responses.

The `hierarchy` package is a framework-independent Python API. The FastMCP adapter exposes the same
render, create, and update operations as MCP tools. The adapter translates JSON-safe inputs and
resolves every model-supplied source, theme, output, and plan path beneath configured workspace
roots. The renderer accepts in-memory data or an explicitly selected JSON/YAML file. It reads
packaged or caller-selected CSS and can write one HTML document. Source values are validated and
HTML-escaped before rendering. Theme names and output filenames are base names, so path authority
remains with the explicit source, themes-folder, and output-folder parameters.

Durable plan creation normalizes hierarchy input into a same-named JSON source and HTML rendering.
The JSON file stores ordered item text, completion state, children, and presentation parameters.
Mutation resolves one item by an exact dotted path or an exact unique title, applies one requested
change, rewrites the JSON source, and regenerates the HTML. Dotted paths are parsed by component;
they are not matched as text prefixes. The JSON source remains authoritative, while HTML remains a
derived read-only report. Before an MCP mutation, the adapter reauthorizes any custom-theme folder
stored in the plan because another process can edit the JSON source after creation.

## Claim compatibility

The CLI adapter preserves the accepted `claim.py` registry, journal, output, and exit-code contracts as an operational fallback and black-box compatibility surface. MCP tools use a structured in-process dispatcher rather than capturing standard output. The primary worktree owns one ignored `.codex/agent-claim` state root shared by every linked worktree. A cross-platform exclusive OS lock is applied directly to its repository-global registry, whose file identity is preserved by in-place updates. Immediately after every legacy registry lock acquisition, including read-only access, and after each canonical operation-lock acquisition, the adapter verifies a locked regular-file descriptor and a current non-symlink regular-file path. POSIX additionally requires live links and exact device and inode identity; Windows relies on its locked-open replacement and deletion exclusion because link, device, and inode fields are not portable there. A concurrent legacy-marker handoff causes bounded re-resolution before any read or migration write instead of using a stale descriptor. This disk lock remains the cross-process ownership authority on POSIX and Windows, while unrelated repositories can proceed concurrently inside one MCP server.

State is created lazily by mutating operations; status and reporting keep an absent repository write-free. Canonical `state.json` records schema version 1, state-layout version 2, migration status, and fresh or legacy origin. Migration accepts only empty legacy state, preserves event history, and installs the exact incompatible registry-directory child marker and regular event-file marker at the old Git-metadata paths. A live legacy registry is drain-only through exact release. Versioned canonical state rejects incomplete, replaced-marker, or contradictory dual-location rollouts without mutation.

Claims may own one provider-opaque work-item activity, one file domain, or one policy-bounded named resource. Work-item IDs contend independently of path and resource ownership. Resource deadlines record expected release, hard stop, cleanup grace, and evidenced extensions. Release removes only the exact named claim; work-item claims also journal a terminal disposition and optional blocked reference. Reports reconstruct work-item segments and diagnose incomplete or contradictory history. The MCP and CLI adapters only translate these engine outcomes.

## Verification boundary

Verification operations are deliberately composable rather than embedding `dev-methodology` policy. The later methodology retrofit can call these primitives and continue to own methodology-specific profiles and expectations.

## Skill-loading boundary

The server provides path-free catalog listing and content retrieval, but it does not claim that a model has retained a skill. The explicit `skill_find` operation returns the precedence-selected manifest path so callers can pass it to filesystem-oriented operations such as `skill_validate`. Each agent harness owns context insertion and per-task load receipts. The server reports immutable manifest content and digests so a harness can bind evidence to exact bytes.

One catalog snapshot is built lazily per server process. When the process working directory resolves beneath an allowed workspace, the adapter prepends recursive `<cwd>/.agents/skills` and `<cwd>/.codex/skills` project roots to the configured user roots. This gives project definitions precedence without moving project-context rules into the catalog domain. Ordinary list and load operations reuse the snapshot, eliminating repeated tree scans. `skill_refresh` builds a complete replacement outside the publication lock and then swaps it atomically, so readers observe either the old or new revision. Resource paths are part of the catalog revision; resource bytes remain progressively loaded and carry an independent digest.

Extension loading is an opt-in catalog-domain composition. For each requested base name, the
catalog can independently resolve `<base-name>.extension` from the same immutable snapshot. The
loader appends the complete extension after the base document and returns a digest of the combined
content. It reports the applied extension name without merging resource namespaces. Callers access
extension resources through the extension's own catalog name. Missing extensions are a no-op.

The technology registry is parsed once per server process. A detection call computes owner evidence and manifest dependencies once per requested scope, then evaluates all configured skill predicates against that shared evidence.

## Reference-loading boundary

The adapter authorizes the working project through the configured workspace roots. It then passes that project root, the configured user roots, and the configured filename allowlist to `reference_data`. The domain package does not depend on FastMCP or environment parsing.

For each allowlisted name, the domain checks one direct file in the project root and one direct file in each configured user root. It does not recurse. It deduplicates identical resolved files, then joins all remaining UTF-8 contents with one newline in project-first search order. The model-facing result identifies each source by a path-free scope label and SHA-256 digest.

One reference snapshot is built lazily per server process. The snapshot pairs aggregated content with its digest. `reference_refresh` builds a replacement outside the publication lock and swaps it atomically. Readers observe either the complete old snapshot or the complete new snapshot.

## Filesystem boundaries

The host configures separate user reference roots, user skill roots, and workspace roots. Automatic
project scopes are accepted only when the process working directory is beneath an allowed
workspace. The reference allowlist prevents arbitrary working-project files from becoming
model-readable. Every reference candidate must resolve beneath its selected scope and must be a
regular UTF-8 file. Model-supplied repository, project, verification, validation, worktree,
hierarchy source, theme, output, and plan paths are resolved only beneath their boundaries after
symlink resolution. Skill validation and technology detection repeat containment at each nested
read boundary. Model-facing reference, catalog, validation, and detection results omit configured
host paths; `skill_find` is the narrow operation that intentionally returns one selected manifest
path. Hierarchy tools return resolved output and plan paths because later agent calls use those
paths as mutation inputs. The boundary is reproducibility and host-state protection for ordinary
agent work; it is not a general hostile-code sandbox.

## Transport

The transport is stdio. Process memory is used only for immutable read snapshots; disk remains authoritative and separate server processes continue coordinating claim mutations through repository-global state. An HTTP transport can be added later without changing domain interfaces.

The non-starting identity command reports the package version plus a location-independent digest over installed runtime resources. Evaluators bind that digest together with the launcher digest and server configuration before execution.

An optional evaluation-only middleware writes a separate digest-only tool lifecycle stream beneath an administrator-configured audit root. Exclusive mode owns one file for one server process. Explicit shared mode lets inherited parent and subagent MCP processes append separate random stream identities under a POSIX file lock without sharing call identifiers or process-local sequences. It records a started event before dispatch and a terminal digest after dispatch. A post-dispatch audit write failure never converts a completed mutation into a retryable tool failure; the evaluator instead rejects the incomplete audit stream.
