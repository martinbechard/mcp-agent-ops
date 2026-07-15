# High-Level Architecture

The project uses a domain-and-adapter structure.

```text
MCP host -> FastMCP adapter -> domain service -> Git repository / skill roots
CLI user -> CLI adapter -----^
```

## Domain ownership

- `claims` owns registry locking, scope overlap, worktree selection, lifecycle events, journal maintenance, and reporting.
- `verification` owns deterministic YAML and Markdown checks.
- `skill_catalog` owns root precedence, metadata extraction, digests, and safe content retrieval.

No domain module depends on FastMCP. Adapters translate typed requests to domain calls and translate domain results to stable structured responses.

## Claim compatibility

The first release preserves the current `claim.py` registry, journal, output, and exit-code contracts. The CLI adapter is retained as an operational fallback and as black-box compatibility evidence. MCP tools invoke the same in-process command service, serialized only around standard-stream capture; repository-global file locks remain the cross-process authority.

## Verification boundary

Verification operations are deliberately composable rather than embedding `dev-methodology` policy. The later methodology retrofit can call these primitives and continue to own methodology-specific profiles and expectations.

## Skill-loading boundary

The server provides discovery and content retrieval, but it does not claim that a model has retained a skill. Each agent harness owns context insertion and per-task load receipts. The server reports immutable content digests so a harness can avoid redundant loading safely.

## Transport

The initial transport is stdio. A server process may be short-lived, so no correctness rule relies on process memory. An HTTP transport can be added later without changing domain interfaces.
