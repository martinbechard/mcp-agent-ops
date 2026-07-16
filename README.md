# MCP Agent Operations

`mcp-agent-ops` is a local stdio MCP server for deterministic agent-development operations that otherwise cause repeated shell and generated Python calls.

The initial service owns three capability groups:

- repository claims, worktree isolation, event journaling, archival, and contention reporting;
- reusable YAML and Markdown verification operations;
- structured discovery and on-demand reading of installed Agent Skills.

The domain packages are independent of FastMCP. The installed `mcp-agent-ops` command starts the FastMCP stdio server, while `mcp-agent-ops-claims` preserves a direct CLI surface for claim coordination and recovery.

The initial claim engine, technology detector, and Agent Skill validator are copied from the accepted `dev-methodology` implementations. See `docs/reference/copied-scripts.md` for exact provenance and compatibility coverage.

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

The server uses stdio by default. Configure readable skill roots through `MCP_AGENT_OPS_SKILL_ROOTS`, using the operating system path separator between roots. Configure the methodology-owned technology registry through `MCP_AGENT_OPS_DETECTION_REGISTRY`. Repository arguments remain explicit per tool call.

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
   VERSION=0.1.1
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

Claim registries and event journals live in each target repository's Git common directory. Skill files remain in their installed roots. The MCP process does not hold authoritative claim or skill-load state.
