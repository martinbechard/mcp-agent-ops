# MCP Agent Operations

`mcp-agent-ops` is a local stdio MCP server for deterministic agent-development operations that otherwise cause repeated shell and generated Python calls.

The service owns five capability groups:

- repository claims, worktree isolation, event journaling, archival, and contention reporting;
- reusable YAML and Markdown verification operations;
- snapshot-based discovery and batched loading of installed Agent Skills;
- Agent Skill validation; and
- evidence-based technology-skill detection.

The domain packages are independent of FastMCP. The installed `mcp-agent-ops` command starts the FastMCP stdio server, while `mcp-agent-ops-claims` preserves a direct CLI surface for claim coordination and recovery.

The claim engine, technology detector, and Agent Skill validator began as copies of the accepted `dev-methodology` implementations. See `docs/reference/copied-scripts.md` for exact provenance, intentional adapter changes, and compatibility coverage.

See `docs/reference/mcp-tools.md` for the complete small-call tool and resource surface.

## Install the latest release

The supported distribution is the wheel attached to the [latest GitHub Release](https://github.com/martinbechard/mcp-agent-ops/releases/latest). Do not install the generated source archive when only the runtime server is needed; the wheel excludes tests, documentation, and development dependencies.

On macOS or Linux, install `uv` and an authenticated GitHub CLI, then download and verify the latest release assets:

```bash
release_dir="$(mktemp -d)"
gh release download \
  --repo martinbechard/mcp-agent-ops \
  --pattern '*' \
  --dir "$release_dir"

(
  cd "$release_dir"
  if command -v sha256sum >/dev/null; then
    sha256sum -c SHA256SUMS
  else
    shasum -a 256 -c SHA256SUMS
  fi
)
```

Install the wheel and its tested, locked runtime dependencies into an isolated tool environment:

```bash
uv tool install \
  --python 3.11 \
  --with-requirements "$release_dir/runtime-requirements.txt" \
  "$release_dir"/mcp_agent_ops-*.whl

rm -rf "$release_dir"
```

Running the same procedure after a newer release is published replaces the installed tool version. `uv tool list` reports the installed version and commands.

Verify the installed server package without starting stdio:

```bash
mcp-agent-ops --version
```

## Development

Python 3.11 or newer and `uv` are required for development.

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy src
```

## Local MCP configuration

Configure an MCP host to run:

```text
mcp-agent-ops
```

The server uses stdio by default. Configure all three path boundaries before exposing it to an agent:

- `MCP_AGENT_OPS_SKILL_ROOTS` contains precedence-ordered readable skill roots, separated by the operating system path separator. A root may contain child skill directories or may be one exact skill directory containing `SKILL.md`.
- `MCP_AGENT_OPS_DETECTION_REGISTRY` identifies the trusted methodology-owned technology registry.
- `MCP_AGENT_OPS_WORKSPACE_ROOTS` contains allowed project and worktree roots, separated by the operating system path separator.

Repository, project, verification, worktree, and validation paths supplied through tools must be absolute and resolve beneath their configured boundary. Catalog discovery, skill validation, and technology detection recheck every nested manifest, metadata file, source file, and supporting resource before reading it. The server rejects missing boundary configuration, traversal, and symlink escape rather than granting ambient filesystem access.

The skill catalog is built lazily and reused for the life of the server process. `skill_refresh` atomically publishes a new catalog snapshot after installed skills change. Technology registry configuration is also cached and takes effect after restarting the server. Claim state remains disk-authoritative and coordinates across server processes.

## Create a release

Releases use semantic versions. The Git tag must be `v` followed by the exact `project.version` value in `pyproject.toml`; the release workflow rejects a mismatch.

1. Choose the next version and update `project.version` in `pyproject.toml`.
2. Refresh the lockfile and run the complete local verification:

   ```bash
   uv lock
   uv sync --locked
   uv run pytest
   uv run ruff check .
   uv run mypy src
   ```

3. Commit the version and lockfile, push `main`, and wait for its CI run to succeed:

   ```bash
   VERSION=0.2.1
   git add pyproject.toml uv.lock
   git commit -m "Prepare release v${VERSION}"
   git push origin main
   gh run list --workflow CI --branch main --limit 1
   ```

4. Tag the verified commit and push the tag:

   ```bash
   git tag -a "v${VERSION}" -m "Release v${VERSION}"
   git push origin "v${VERSION}"
   ```

5. Confirm that the Release workflow passed and the release is available:

   ```bash
   gh run list --workflow Release --limit 1
   gh release view "v${VERSION}"
   ```

The tag-triggered workflow reruns tests on Python 3.11, 3.12, and 3.13 before publishing the wheel, `runtime-requirements.txt`, and `SHA256SUMS`. Do not reuse or move a published version tag; increment the package version for the next release.

## State ownership

Claim registries and event journals live in each target repository's Git common directory. Skill files remain authoritative in their installed roots. Process-local catalog and registry snapshots are read versions identified by digests, not independent state stores; publishing or restarting replaces them from disk.
