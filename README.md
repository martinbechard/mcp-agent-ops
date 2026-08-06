# MCP Agent Operations

`mcp-agent-ops` is a local stdio MCP server for deterministic agent-development operations that otherwise cause repeated shell and generated Python calls.

The service owns five capability groups:

- repository claims, worktree isolation, event journaling, archival, and contention reporting;
- reusable YAML and Markdown verification operations;
- snapshot-based discovery and batched loading of installed Agent Skills;
- Agent Skill validation; and
- evidence-based technology-skill detection.

The domain packages are independent of FastMCP. The installed `mcp-agent-ops` command starts the FastMCP stdio server, while `mcp-agent-ops-claims` preserves a direct CLI surface for claim coordination and recovery. Claim callers can select project-files, primary-only backlog, or explicit all-files ownership; project isolation uses a canonical sparse worktree that omits backlog. Every checkout resolves disposable claim state to the primary worktree's ignored `.codex/agent-claim` directory.

The claim engine, technology detector, and Agent Skill validator began as copies of the accepted `dev-methodology` implementations. See `docs/reference/copied-scripts.md` for exact provenance, intentional adapter changes, and compatibility coverage.

See `docs/reference/mcp-tools.md` for the complete small-call tool and resource surface.

## Supported platforms

The stdio server, direct claim CLI, repository locking, skill catalog, verification, and technology detection run natively on:

- macOS with Python 3.11, 3.12, or 3.13;
- Linux with Python 3.11, 3.12, or 3.13; and
- Windows with Python 3.11, 3.12, or 3.13 in releases newer than `v0.4.0`.

Published release `v0.4.0` predates native Windows claim locking. macOS and Linux remain supported by every published release. The optional shared multi-process evaluation audit uses POSIX file locking and remains limited to macOS and Linux; this does not affect ordinary MCP or claim operation on Windows.

## Install the latest release

The supported distribution is the wheel attached to the [latest GitHub Release](https://github.com/martinbechard/mcp-agent-ops/releases/latest). Do not install the generated source archive when only the runtime server is needed; the wheel excludes tests, documentation, and development dependencies.

On Windows, first confirm that the latest release is newer than `v0.4.0`. Then open PowerShell and install `uv` plus the GitHub CLI:

```powershell
winget install --id astral-sh.uv -e
winget install --id GitHub.cli --source winget
gh auth login
```

Open a new terminal after WinGet changes `PATH`, then download and verify the latest release:

```powershell
$releaseDir = Join-Path ([System.IO.Path]::GetTempPath()) "mcp-agent-ops-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $releaseDir | Out-Null

gh release download `
  --repo martinbechard/mcp-agent-ops `
  --pattern '*' `
  --dir $releaseDir

Push-Location $releaseDir
Get-Content .\SHA256SUMS | ForEach-Object {
  $expected, $file = $_ -split '\s+', 2
  $file = $file.TrimStart('*')
  $actual = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLowerInvariant()
  if ($actual -ne $expected.ToLowerInvariant()) {
    throw "Checksum mismatch: $file"
  }
}
Pop-Location
```

Install the wheel with its tested, locked runtime dependencies:

```powershell
$wheels = @(Get-ChildItem $releaseDir -Filter 'mcp_agent_ops-*.whl')
if ($wheels.Count -ne 1) {
  throw "Expected exactly one mcp-agent-ops wheel."
}

uv tool install `
  --python 3.11 `
  --with-requirements (Join-Path $releaseDir 'runtime-requirements.txt') `
  $wheels[0].FullName

mcp-agent-ops --version
mcp-agent-ops --identity-json
uv tool dir --bin
```

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
mcp-agent-ops --identity-json
```

The JSON identity includes a location-independent SHA-256 digest over installed runtime resources. Evaluation runners can pin both that runtime digest and the launcher executable digest instead of treating a small console-script wrapper as the server implementation.

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

When the server starts with its working directory beneath a configured workspace root, it automatically overlays recursively discovered skills from `<cwd>/.agents/skills` and `<cwd>/.codex/skills` ahead of the configured user roots. The `.agents` project root has precedence over the `.codex` project root. Nested project skill directories are supported; duplicate skill names inside either one project root are rejected as ambiguous. `skill_refresh` rescans both project and configured roots.

Repository, project, verification, worktree, and validation paths supplied through tools must be absolute and resolve beneath their configured boundary. Name-based skill validation uses the same catalog lookup as skill loading. Explicit skill-validation paths may also target unpublished skills anywhere beneath the authorized working project, without adding those paths to catalog discovery. Catalog discovery, skill validation, and technology detection recheck every nested manifest, metadata file, source file, and supporting resource before reading it. The server rejects missing boundary configuration, traversal, and symlink escape rather than granting ambient filesystem access.

The skill catalog is built lazily and reused for the life of the server process. `skill_refresh` atomically publishes a new catalog snapshot after installed skills change. Technology registry configuration is also cached and takes effect after restarting the server. Claim state remains disk-authoritative and coordinates across server processes.

### Junie on macOS

Junie reads MCP configuration from `~/.junie/mcp/mcp.json` for user scope or `.junie/mcp/mcp.json` beneath one project. In the IDE, open **Settings | Tools | Junie | MCP Settings**.

Use the absolute executable directory reported by `uv tool dir --bin`. Replace `YOUR_NAME` and the workspace path with existing absolute paths:

```json
{
  "mcpServers": {
    "mcp-agent-ops": {
      "command": "/Users/YOUR_NAME/.local/bin/mcp-agent-ops",
      "args": [],
      "env": {
        "MCP_AGENT_OPS_SKILL_ROOTS": "/Users/YOUR_NAME/.agents/skills:/Users/YOUR_NAME/.codex/skills",
        "MCP_AGENT_OPS_DETECTION_REGISTRY": "/Users/YOUR_NAME/.agents/skills/detect-technology-skills/references/technology-skill-detection-registry.yaml",
        "MCP_AGENT_OPS_WORKSPACE_ROOTS": "/Users/YOUR_NAME/dev"
      }
    }
  }
}
```

macOS and Linux path lists use colons. On Linux, use the same configuration with Linux paths such as `/home/YOUR_NAME`.

### Junie on Windows

Junie reads MCP configuration from `%USERPROFILE%\.junie\mcp\mcp.json` for user scope or `.junie\mcp\mcp.json` beneath one project. In the IDE, the same configuration is available under **Settings | Tools | Junie | MCP Settings**.

Use the absolute executable directory reported by `uv tool dir --bin`. Replace the example user and workspace paths with existing absolute paths:

```json
{
  "mcpServers": {
    "mcp-agent-ops": {
      "command": "C:\\Users\\YOUR_NAME\\.local\\bin\\mcp-agent-ops.exe",
      "args": [],
      "env": {
        "MCP_AGENT_OPS_SKILL_ROOTS": "C:\\Users\\YOUR_NAME\\.agents\\skills;C:\\Users\\YOUR_NAME\\.codex\\skills",
        "MCP_AGENT_OPS_DETECTION_REGISTRY": "C:\\Users\\YOUR_NAME\\.agents\\skills\\detect-technology-skills\\references\\technology-skill-detection-registry.yaml",
        "MCP_AGENT_OPS_WORKSPACE_ROOTS": "C:\\Users\\YOUR_NAME\\dev"
      }
    }
  }
}
```

Windows path lists use semicolons. Restart Junie after saving the configuration, then confirm that `mcp-agent-ops` is active and exposes its tools in MCP Settings.

Evaluation runners may configure `MCP_AGENT_OPS_AUDIT_LOG` plus `MCP_AGENT_OPS_AUDIT_ROOTS` to create one exclusive digest-only JSON Lines tool-call trace. When a harness starts inherited MCP servers for a parent and subagent, set `MCP_AGENT_OPS_AUDIT_SHARED=true` plus a 32-character lowercase hexadecimal `MCP_AGENT_OPS_AUDIT_SESSION_ID`; each process then writes a separate random stream identity and process-local sequence into the same owner-only file under a POSIX file lock. Both modes record only canonical tool name, lifecycle status, call identity, sequence, and argument or result digests. Shared version-two records also carry the session and process stream identities, and their terminal records carry bounded canonical outcomes for supported deterministic operations. `skill_validate` records `VALID` when its structured `ok` field is true and `FINDINGS` when it is false. `skill_refresh` records `CATALOG` when its published `skills` snapshot is non-empty and `EMPTY` when it is empty. These labels reveal neither skill content nor validation findings. The trace never stores arguments, returned content, prompts, or configured paths. Do not configure this trace for ordinary sessions that do not need evaluator-owned call evidence.

An evaluator can also set `MCP_AGENT_OPS_REQUIRED_RUNTIME_DIGEST` to the pinned value returned by `--identity-json`. The server checks it before importing FastMCP or starting stdio and fails closed when the installed runtime has drifted.

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
   VERSION=0.3.0
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

Claim registries and event journals live beneath each target repository's primary-worktree `.codex/agent-claim` directory. Read-only status and reporting do not create absent state. A first mutating operation migrates only empty legacy Git-metadata state, preserves history and recoverable backups, and installs incompatible markers at the old paths so an older helper cannot create a split registry. Live legacy claims are drain-only through exact release. Skill files remain authoritative in their installed roots. Process-local catalog and registry snapshots are read versions identified by digests, not independent state stores; publishing or restarting replaces them from disk.
