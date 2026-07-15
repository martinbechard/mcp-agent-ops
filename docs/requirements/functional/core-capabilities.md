# Core Functional Capabilities

## Claims

- The service exposes structured operations for claim status, acquisition, extension, heartbeat, release, journal maintenance, and contention reporting.
- MCP and CLI claim operations preserve the stable outcomes and exit-code semantics of the existing `agent-claim` command.
- Claims from linked worktrees coordinate through one registry in the Git common directory.
- Claim mutations append diagnostic events without making journal availability part of ownership safety.

## Verification

- The service validates YAML syntax while detecting duplicate mapping keys.
- The service verifies local Markdown links without following remote URLs.
- Results identify every checked file and return structured diagnostics suitable for agent decisions.
- Verification never mutates the inspected repository.

## Skill Catalog

- The service discovers skills from configured roots by reading complete `SKILL.md` files.
- Catalog entries include stable names, descriptions, paths, content digests, and available supporting resources.
- A caller can retrieve one complete skill or one supporting resource on demand.
- Duplicate skill names resolve by configured root precedence and remain visible as shadowed entries.
- Resolved resource paths cannot escape the owning skill directory.

## Protocol

- The service starts over stdio without writing non-protocol output to standard output.
- Tool results are structured and schema-described.
- Skill content is available as MCP resources and through tool fallbacks for tool-only hosts.
