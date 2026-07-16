# Runtime and Safety Requirements

- Support Python 3.11 through 3.13.
- Pin FastMCP exactly and commit the resolved dependency lock.
- Keep the domain layer importable without FastMCP initialization.
- Treat model-supplied repository, project, worktree, validation, and requested resource paths as untrusted filesystem inputs.
- Require administrator-configured workspace and skill roots before resolving model-supplied paths.
- Require model-supplied workspace and skill paths to be absolute and contained after symlink resolution.
- Recheck every nested skill manifest, adapter metadata file, technology source, owner manifest, owner-evidence file, and resource at its read boundary.
- Reject nested paths that escape their configured roots through symlinks and omit configured host paths from model-facing diagnostics.
- Preserve atomic claim registry writes and operating-system file locking.
- Keep authoritative claim state on disk so separate stdio server processes coordinate correctly.
- Permit claim operations against unrelated repositories to run concurrently within one server process.
- Keep catalog snapshots immutable for readers and atomically replace them only through explicit refresh.
- Bound batch counts and encoded response sizes before returning skill or resource content.
- Test protocol behavior both in memory and through a real stdio subprocess.
- Test claim contention with independent processes against one temporary Git repository.
