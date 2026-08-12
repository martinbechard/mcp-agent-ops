# Runtime and Safety Requirements

- Support Python 3.11 through 3.13.
- Pin FastMCP exactly and commit the resolved dependency lock.
- Keep the domain layer importable without FastMCP initialization.
- Treat model-supplied repository, project, worktree, validation, hierarchy source, theme, output,
  and plan paths, requested resource paths, and relative reference paths as untrusted filesystem inputs.
- Reject symbolic-link hierarchy-plan sources and outputs before mutation.
- Resolve dotted hierarchy targets by complete one-based path components, never by text-prefix matching.
- Require administrator-configured workspace and skill roots before resolving model-supplied paths.
- Require model-supplied workspace and skill paths to be absolute and contained after symlink resolution.
- Resolve every hierarchy MCP file or folder path beneath `MCP_AGENT_OPS_WORKSPACE_ROOTS` before domain access or mutation.
- Reauthorize a durable plan's stored custom-theme folder before each MCP mutation.
- Recheck every nested skill manifest, adapter metadata file, technology source, owner manifest, owner-evidence file, and resource at its read boundary.
- Publish project references only beneath conventional agent and skill folders when the working project is authorized.
- Reject unsafe relative reference paths and omit non-files, non-UTF-8 content, and reference symlinks that escape their selected folder.
- Reject nested paths that escape their configured roots through symlinks. Omit configured host
  paths from ordinary model-facing results and validation diagnostics, but make catalog-construction
  failures identify the invalid manifest, resolved target, configured roots, and exact root-setting
  repair required from the administrator.
- Preserve atomic in-place claim registry writes under an exclusive operating-system lock applied directly to the stable registry file.
- Support claim coordination and ordinary stdio MCP operation on POSIX and Windows without a compatibility subsystem.
- Keep broad claim-domain selection explicit and mutually exclusive; never infer all-files from a repository root argument.
- Derive isolated checkout locations beneath the primary worktree, require the operational root to be ignored, and configure sparse checkout before populating files.
- Keep work-item, path, and resource scope independent, and validate each public combination before registry mutation.
- Resolve configured resource deadlines from `PROJECT.yaml` and reject incomplete, mismatched, or over-maximum requests atomically.
- Keep authoritative claim state on disk so separate stdio server processes coordinate correctly.
- Permit claim operations against unrelated repositories to run concurrently within one server process.
- Keep reference and skill catalog snapshots immutable for readers and atomically replace them only through explicit refresh.
- Bound batch counts and encoded response sizes before returning reference, skill, or resource content.
- Permit an evaluation audit log only beneath explicitly configured audit roots, create it exclusively by default, reject symlink substitution, and never retain tool arguments or result content.
- Permit explicit multi-process evaluation audit only for an owner-only regular file, with a distinct random stream identity per server process and POSIX-locked append writes.
- When configured, verify the required installed-runtime digest before importing the MCP transport or starting stdio.
- Test protocol behavior both in memory and through a real stdio subprocess.
- Test claim contention with independent processes against one temporary Git repository.
