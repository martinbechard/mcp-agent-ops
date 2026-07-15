# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Publishes concise typed FastMCP tools and resources over the copied scripts and domain services.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import os
from collections.abc import Sequence
from pathlib import Path

from fastmcp import FastMCP

from mcp_agent_ops.claims.service import ClaimCommandResult, run_claim_command
from mcp_agent_ops.skill_catalog.catalog import SkillCatalog
from mcp_agent_ops.skill_catalog.models import LoadedSkill, LoadedSkillResource, SkillCatalogResult
from mcp_agent_ops.skill_validation.service import SkillValidationResult, validate_skills
from mcp_agent_ops.technology_detection.service import TechnologyDetectionResult
from mcp_agent_ops.technology_detection.service import detect_technology_skills as detect_domain
from mcp_agent_ops.verification.markdown_links import verify_markdown_links as verify_markdown_links_domain
from mcp_agent_ops.verification.models import VerificationReport
from mcp_agent_ops.verification.yaml_files import verify_yaml as verify_yaml_domain


def _append_values(arguments: list[str], option: str, values: Sequence[str] | None) -> None:
    for value in values or []:
        arguments.extend((option, value))


def _append_scope(
    arguments: list[str],
    files: Sequence[str] | None,
    trees: Sequence[str] | None,
    resources: Sequence[str] | None,
    all_files: bool,
    scope_reason: str | None,
    compat_file_directories: bool,
) -> None:
    _append_values(arguments, "--file", files)
    _append_values(arguments, "--tree", trees)
    _append_values(arguments, "--resource", resources)
    if all_files:
        arguments.append("--all-files")
    if scope_reason:
        arguments.extend(("--scope-reason", scope_reason))
    if compat_file_directories:
        arguments.append("--compat-file-directories")


def configured_skill_roots() -> list[Path]:
    """Read precedence-ordered skill roots from the server environment.

    Returns:
        Expanded paths from `MCP_AGENT_OPS_SKILL_ROOTS`, split using the host operating
        system path separator. An absent or empty variable produces an empty catalog.
    """
    raw = os.environ.get("MCP_AGENT_OPS_SKILL_ROOTS", "")
    return [Path(value).expanduser() for value in raw.split(os.pathsep) if value]


def configured_detection_registry() -> Path | None:
    """Return the configured methodology-owned technology detection registry, if any."""
    value = os.environ.get("MCP_AGENT_OPS_DETECTION_REGISTRY")
    return Path(value).expanduser() if value else None


def create_server(
    skill_roots: Sequence[Path] | None = None,
    detection_registry: Path | None = None,
) -> FastMCP:
    """Create the stateless MCP agent-operations server.

    Args:
        skill_roots: Optional precedence-ordered roots used instead of environment
            configuration. A fresh catalog snapshot is built for every skill operation.
        detection_registry: Optional methodology-owned technology detection registry used
            instead of `MCP_AGENT_OPS_DETECTION_REGISTRY`.

    Returns:
        A FastMCP server ready for in-memory testing or stdio execution.

    Claim tools mutate target Git-global claim state. Verification and skill operations
    are read-only. No correctness rule relies on server-process memory.
    """
    roots = list(skill_roots) if skill_roots is not None else configured_skill_roots()
    registry = detection_registry or configured_detection_registry()
    mcp = FastMCP("MCP Agent Operations")

    def catalog() -> SkillCatalog:
        return SkillCatalog.from_roots(roots)

    @mcp.tool
    def claim_status(repository: str) -> ClaimCommandResult:
        """Return the authoritative live claim registry for one Git repository."""
        return run_claim_command(["--repo", repository, "status"])

    @mcp.tool
    def claim_acquire(
        repository: str,
        claim_id: str,
        agent: str,
        task: str,
        root_task_id: str,
        files: list[str] | None = None,
        trees: list[str] | None = None,
        resources: list[str] | None = None,
        all_files: bool = False,
        scope_reason: str | None = None,
        parent_claim_id: str | None = None,
        branch: str | None = None,
        worktree_path: str | None = None,
        base: str = "HEAD",
        allow_recovery: bool = False,
        compat_file_directories: bool = False,
    ) -> ClaimCommandResult:
        """Atomically acquire narrow file, tree, or resource ownership.

        Returns PRIMARY, ISOLATE, WAIT, ISOLATE_REQUIRED, RECOVERY_REQUIRED, RECOVER,
        or a structured rejection with the copied claim engine's stable exit code.
        """
        arguments = [
            "--repo",
            repository,
            "acquire",
            "--claim-id",
            claim_id,
            "--agent",
            agent,
            "--task",
            task,
            "--root-task-id",
            root_task_id,
            "--base",
            base,
        ]
        if parent_claim_id:
            arguments.extend(("--parent-claim-id", parent_claim_id))
        if branch:
            arguments.extend(("--branch", branch))
        if worktree_path:
            arguments.extend(("--worktree-path", worktree_path))
        if allow_recovery:
            arguments.append("--allow-recovery")
        _append_scope(arguments, files, trees, resources, all_files, scope_reason, compat_file_directories)
        return run_claim_command(arguments)

    @mcp.tool
    def claim_extend(
        repository: str,
        claim_id: str,
        files: list[str] | None = None,
        trees: list[str] | None = None,
        resources: list[str] | None = None,
        all_files: bool = False,
        scope_reason: str | None = None,
        compat_file_directories: bool = False,
    ) -> ClaimCommandResult:
        """Atomically add net-new scope to one active claim without weakening existing ownership."""
        arguments = ["--repo", repository, "extend", "--claim-id", claim_id]
        _append_scope(arguments, files, trees, resources, all_files, scope_reason, compat_file_directories)
        return run_claim_command(arguments)

    @mcp.tool
    def claim_heartbeat(repository: str, claim_id: str) -> ClaimCommandResult:
        """Refresh one active claim heartbeat in the repository-global registry."""
        return run_claim_command(["--repo", repository, "heartbeat", "--claim-id", claim_id])

    @mcp.tool
    def claim_release(repository: str, claim_id: str, no_change: bool = False) -> ClaimCommandResult:
        """Release a clean committed claim or an explicitly declared no-change claim."""
        arguments = ["--repo", repository, "release", "--claim-id", claim_id]
        if no_change:
            arguments.append("--no-change")
        return run_claim_command(arguments)

    @mcp.tool
    def claim_maintain_journal(repository: str, hot_days: int = 2) -> ClaimCommandResult:
        """Archive complete UTC claim-event days while retaining the configured hot window."""
        return run_claim_command(
            ["--repo", repository, "maintain-journal", "--hot-days", str(hot_days)]
        )

    @mcp.tool
    def claim_report(repository: str, since: str = "2d", output_format: str = "json") -> ClaimCommandResult:
        """Report claim contention and lifecycle metrics without mutating the live registry."""
        return run_claim_command(
            ["--repo", repository, "report", "--since", since, "--format", output_format]
        )

    @mcp.tool
    def verify_yaml(repository_root: str, paths: list[str]) -> VerificationReport:
        """Validate exact YAML files, including duplicate keys, with structured diagnostics."""
        return verify_yaml_domain(Path(repository_root), paths)

    @mcp.tool
    def verify_markdown_links(
        repository_root: str,
        patterns: list[str] | None = None,
    ) -> VerificationReport:
        """Verify local Markdown targets and anchors selected by simple root-relative globs."""
        return verify_markdown_links_domain(Path(repository_root), patterns or ["**/*.md"])

    @mcp.tool
    def skill_list() -> SkillCatalogResult:
        """List configured skills with descriptions, digests, resources, and shadowing evidence."""
        return catalog().result()

    @mcp.tool
    def skill_read(name: str) -> LoadedSkill:
        """Read one complete precedence-resolved `SKILL.md` document on demand."""
        return catalog().read_skill(name)

    @mcp.tool
    def skill_read_resource(name: str, resource_path: str) -> LoadedSkillResource:
        """Read one supporting skill resource without permitting directory traversal."""
        return catalog().read_resource(name, resource_path)

    @mcp.tool
    def skill_validate(paths: list[str]) -> SkillValidationResult:
        """Validate Agent Skill roots, directories, or exact `SKILL.md` files."""
        return validate_skills([Path(path).expanduser() for path in paths])

    @mcp.tool
    def detect_technology_skills(project_root: str, scopes: list[str]) -> TechnologyDetectionResult:
        """Detect required technology skills for project scopes using the configured registry."""
        if registry is None:
            raise ValueError("Technology detection requires MCP_AGENT_OPS_DETECTION_REGISTRY configuration.")
        current_catalog = catalog().result()
        skills_root = roots[0] if roots else registry.parent
        return detect_domain(
            Path(project_root),
            scopes,
            registry,
            skills_root,
            [entry.name for entry in current_catalog.skills],
        )

    @mcp.resource("skill://catalog", mime_type="application/json")
    def skill_catalog_resource() -> str:
        """Return the current structured skill catalog as JSON."""
        return catalog().result().model_dump_json()

    @mcp.resource("skill://{name}", mime_type="text/markdown")
    def skill_document_resource(name: str) -> str:
        """Return one complete selected skill document by resource URI."""
        return catalog().read_skill(name).content

    @mcp.resource("skill-resource://{name}/{resource_path*}")
    def skill_supporting_resource(name: str, resource_path: str) -> str | bytes:
        """Return one selected supporting skill resource by safe resource URI."""
        loaded = catalog().read_resource(name, resource_path)
        if loaded.content is not None:
            return loaded.content
        if loaded.data_base64 is None:
            raise ValueError("Skill resource has neither text nor binary content.")
        import base64

        return base64.b64decode(loaded.data_base64)

    return mcp


def run_server() -> None:
    """Run the configured MCP agent-operations server over stdio until its host disconnects."""
    create_server().run(transport="stdio", show_banner=False)
