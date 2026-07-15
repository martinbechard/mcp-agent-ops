# Agent Instructions

## File Placement

- Before creating a new file, read `docs/project-taxonomy.md` and place the file in the most specific matching category.
- If no category fits, update `docs/project-taxonomy.md` before creating the file.
- Do not reclassify existing files unless the task specifically requires moving or renaming them.

## Code Artifact Headers

- Apply the `code-comments` skill to executable code artifacts.
- Use this exact copyright statement: `Copyright (c) 2026 Martin.Bechard@DevConsult.ca`.
- Apply code headers to source and test code, not configuration, documentation, or data files.

## Architecture

- Keep claims, verification, and skill-catalog behavior independent of FastMCP and CLI parsing.
- MCP and CLI adapters may translate inputs and outputs but must not duplicate domain rules.
- Claim authority belongs to the repository-global registry, never MCP process memory.
- Runtime repository paths and skill roots are untrusted inputs; resolve them against explicit allowed roots before access.

## Verification

- Use `uv run pytest` for the full test suite.
- Use `uv run ruff check .` and `uv run mypy src` for static verification.
- Add real stdio and multi-process tests when changing transport or claim concurrency behavior.

