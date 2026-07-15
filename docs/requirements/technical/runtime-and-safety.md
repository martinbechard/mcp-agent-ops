# Runtime and Safety Requirements

- Support Python 3.11 through 3.13.
- Pin FastMCP exactly and commit the resolved dependency lock.
- Keep the domain layer importable without FastMCP initialization.
- Treat repository paths, skill roots, and requested resource paths as untrusted filesystem inputs.
- Preserve atomic claim registry writes and operating-system file locking.
- Keep authoritative claim state on disk so separate stdio server processes coordinate correctly.
- Test protocol behavior both in memory and through a real stdio subprocess.
- Test claim contention with independent processes against one temporary Git repository.

