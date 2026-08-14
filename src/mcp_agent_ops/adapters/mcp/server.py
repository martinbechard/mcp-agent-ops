# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Publishes typed FastMCP operations with safe hierarchy, project skill, and reference paths.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import yaml
from fastmcp import FastMCP
from pydantic import Field

from mcp_agent_ops.adapters.mcp.audit import ToolAuditLog, ToolAuditMiddleware
from mcp_agent_ops.claims.service import ClaimCommandResult, run_claim_command
from mcp_agent_ops.hierarchy import (
    HierarchyPlanUpdateResult,
)
from mcp_agent_ops.hierarchy import (
    create_hierarchy_plan as create_hierarchy_plan_domain,
)
from mcp_agent_ops.hierarchy import (
    render_hierarchy_html as render_hierarchy_html_domain,
)
from mcp_agent_ops.hierarchy import (
    update_hierarchy_plan as update_hierarchy_plan_domain,
)
from mcp_agent_ops.reference_data.catalog import ReferenceCatalog
from mcp_agent_ops.reference_data.models import (
    PublishedReferenceCatalog,
    ReferenceLoadResult,
)
from mcp_agent_ops.skill_catalog.catalog import SkillCatalog, SkillRootEscapeError
from mcp_agent_ops.skill_catalog.models import (
    BatchLoadedSkill,
    FoundSkill,
    LoadedSkillResource,
    PublishedSkillCatalog,
    SkillLoadResult,
    SkillResourceLoadResult,
    SkillResourceRequest,
)
from mcp_agent_ops.skill_validation.service import SkillValidationResult, validate_skills
from mcp_agent_ops.technology_detection.engine import load_yaml as load_detection_registry
from mcp_agent_ops.technology_detection.service import TechnologyDetectionResult
from mcp_agent_ops.technology_detection.service import detect_technology_skills as detect_domain
from mcp_agent_ops.verification.markdown_links import verify_markdown_links as verify_markdown_links_domain
from mcp_agent_ops.verification.models import VerificationReport
from mcp_agent_ops.verification.paths import resolve_within_roots
from mcp_agent_ops.verification.yaml_files import verify_yaml as verify_yaml_domain

AUDITED_TOOL_NAMES = frozenset({
    "claim_acquire",
    "claim_extend",
    "claim_extend_deadline",
    "claim_heartbeat",
    "claim_maintain_journal",
    "claim_release",
    "claim_report",
    "claim_reset",
    "claim_status",
    "create_hierarchy_plan",
    "detect_technology_skills",
    "reference_load",
    "reference_refresh",
    "render_hierarchy_html",
    "skill_find",
    "skill_list",
    "skill_load",
    "skill_read",
    "skill_read_resource",
    "skill_refresh",
    "skill_resource_load",
    "skill_validate",
    "update_hierarchy_plan",
    "verify_markdown_links",
    "verify_yaml",
})

_ProjectFilesScope = Annotated[
    bool,
    Field(
        description=(
            "Select project files excluding backlog. Mutually exclusive with backlog and all_files; "
            "requires scope_reason. Eligible isolation is placed at the canonical primary-worktree "
            ".worktrees/<claim-id> path with backlog omitted by sparse checkout."
        )
    ),
]
_BacklogScope = Annotated[
    bool,
    Field(
        description=(
            "Select the complete primary-worktree-only backlog. Mutually exclusive with project_files "
            "and all_files; returns SHARED_CHECKOUT_REQUIRED from another checkout."
        )
    ),
]
_AllFilesScope = Annotated[
    bool,
    Field(
        description=(
            "Select the primary-worktree-only union of project files and backlog. Mutually exclusive "
            "with project_files and backlog; requires scope_reason."
        )
    ),
]
_ScopeReason = Annotated[
    str | None,
    Field(
        description=(
            "Bounded coordination-only reason required for tree, project_files, and all_files ownership."
        )
    ),
]


def _append_values(arguments: list[str], option: str, values: Sequence[str] | None) -> None:
    for value in values or []:
        arguments.extend((option, value))


def _append_scope(
    arguments: list[str],
    files: Sequence[str] | None,
    trees: Sequence[str] | None,
    resources: Sequence[str] | None,
    project_files: bool,
    backlog: bool,
    all_files: bool,
    scope_reason: str | None,
    compat_file_directories: bool,
) -> None:
    _append_values(arguments, "--file", files)
    _append_values(arguments, "--tree", trees)
    _append_values(arguments, "--resource", resources)
    if project_files:
        arguments.append("--project-files")
    if backlog:
        arguments.append("--backlog")
    if all_files:
        arguments.append("--all-files")
    if scope_reason:
        arguments.extend(("--scope-reason", scope_reason))
    if compat_file_directories:
        arguments.append("--compat-file-directories")


def _append_resource_timing(
    arguments: list[str],
    resource_class: str | None,
    resource_id: str | None,
    expected_duration_seconds: int | None,
    requested_hard_stop_duration_seconds: int | None,
) -> None:
    values = (
        ("--resource-class", resource_class),
        ("--resource-id", resource_id),
        ("--expected-duration-seconds", expected_duration_seconds),
        ("--requested-hard-stop-duration-seconds", requested_hard_stop_duration_seconds),
    )
    for option, value in values:
        if value is not None:
            arguments.extend((option, str(value)))


def configured_skill_roots() -> list[Path]:
    """Read precedence-ordered skill roots from the server environment.

    Returns:
        Expanded paths from `MCP_AGENT_OPS_SKILL_ROOTS`, split using the host operating
        system path separator. An absent or empty variable produces an empty catalog.
    """
    raw = os.environ.get("MCP_AGENT_OPS_SKILL_ROOTS", "")
    return [Path(value).expanduser() for value in raw.split(os.pathsep) if value]


def configured_reference_roots() -> list[Path]:
    """Read ordered recursive user reference folders from the server environment.

    Returns:
        Expanded paths from `MCP_AGENT_OPS_REFERENCE_ROOTS`, split using the host
        operating-system path separator. Empty configuration provides no user folders.
    """
    raw = os.environ.get("MCP_AGENT_OPS_REFERENCE_ROOTS", "")
    return [Path(value).expanduser() for value in raw.split(os.pathsep) if value]


def _skill_catalog_error_message(
    error: OSError | UnicodeError | ValueError | yaml.YAMLError,
    configured_user_roots: Sequence[Path],
) -> str:
    """Translate a catalog construction failure into an administrator-actionable message."""
    if isinstance(error, SkillRootEscapeError):
        configured_roots = os.pathsep.join(
            str(root) for root in error.configured_roots
        ) or "(none)"
        suggested_roots = [
            *(root.expanduser().resolve() for root in configured_user_roots),
            error.resolved_manifest.parent,
        ]
        unique_suggested_roots = list(dict.fromkeys(suggested_roots))
        setting = os.pathsep.join(str(root) for root in unique_suggested_roots)
        return (
            "Configured skill catalog is invalid. A discovered skill manifest resolves "
            "outside every configured skill root. "
            f"Discovered manifest: {error.discovered_manifest}. "
            f"Resolved manifest: {error.resolved_manifest}. "
            f"Configured skill roots: {configured_roots}. "
            f'Set MCP_AGENT_OPS_SKILL_ROOTS="{setting}" and restart the MCP server.'
        )
    return (
        f"Configured skill catalog is invalid. {error} "
        "Correct the reported skill or remove its containing configured root from "
        "MCP_AGENT_OPS_SKILL_ROOTS, then restart the MCP server."
    )


def configured_detection_registry() -> Path | None:
    """Return the configured methodology-owned technology detection registry, if any."""
    value = os.environ.get("MCP_AGENT_OPS_DETECTION_REGISTRY")
    return Path(value).expanduser() if value else None


def configured_workspace_roots() -> list[Path]:
    """Read administrator-configured roots for model-supplied repository paths."""
    raw = os.environ.get("MCP_AGENT_OPS_WORKSPACE_ROOTS", "")
    return [Path(value).expanduser() for value in raw.split(os.pathsep) if value]


def _hierarchy_roots(workspace_roots: Sequence[Path]) -> list[Path]:
    """Extend hierarchy-only access to Codex's conventional visualization folder."""
    return [*workspace_roots, Path.home() / ".codex" / "visualizations"]


def _within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _project_skill_roots(project_root: Path, workspace_roots: Sequence[Path]) -> list[Path]:
    """Return safe conventional project skill roots when the project is in scope."""
    resolved_project = project_root.expanduser().resolve()
    resolved_workspaces = [root.expanduser().resolve() for root in workspace_roots]
    if not any(_within_root(resolved_project, root) for root in resolved_workspaces):
        return []
    roots = [
        resolved_project / ".agents" / "skills",
        resolved_project / ".codex" / "skills",
    ]
    resolved_roots = [root.resolve() for root in roots]
    if not all(_within_root(root, resolved_project) for root in resolved_roots):
        raise ValueError("Project skill root resolves outside the project root.")
    return resolved_roots


def _project_reference_roots(
    project_root: Path,
    workspace_roots: Sequence[Path],
) -> list[Path]:
    """Return project agent and skill folders when the project is in scope.

    Args:
        project_root: Working project whose local agent references may be published.
        workspace_roots: Configured roots authorized to contain working projects.

    Returns:
        The project ``.agents`` and ``.codex/skills`` folders, or an empty list when the
        project is outside every authorized workspace.

    Raises:
        ValueError: If either conventional folder resolves outside the project root.
    """
    resolved_project = project_root.expanduser().resolve()
    resolved_workspaces = [root.expanduser().resolve() for root in workspace_roots]
    if not any(_within_root(resolved_project, root) for root in resolved_workspaces):
        return []
    roots = [resolved_project / ".agents", resolved_project / ".codex" / "skills"]
    resolved_roots = [root.resolve() for root in roots]
    if not all(_within_root(root, resolved_project) for root in resolved_roots):
        raise ValueError("Project reference root resolves outside the project root.")
    return resolved_roots


def configured_audit_log() -> Path | None:
    """Return the evaluator-controlled digest-only audit log path, if configured."""
    value = os.environ.get("MCP_AGENT_OPS_AUDIT_LOG")
    return Path(value).expanduser() if value else None


def configured_audit_roots() -> list[Path]:
    """Read administrator-configured roots permitted to contain an MCP audit log."""
    raw = os.environ.get("MCP_AGENT_OPS_AUDIT_ROOTS", "")
    return [Path(value).expanduser() for value in raw.split(os.pathsep) if value]


def configured_audit_shared() -> bool:
    """Return whether several inherited MCP processes may share one audit file."""
    raw = os.environ.get("MCP_AGENT_OPS_AUDIT_SHARED", "false").strip().lower()
    if raw not in {"false", "true"}:
        raise ValueError("MCP_AGENT_OPS_AUDIT_SHARED must be true or false.")
    return raw == "true"


def configured_audit_session_id() -> str | None:
    """Return the evaluator-generated identity that binds shared audit streams."""
    return os.environ.get("MCP_AGENT_OPS_AUDIT_SESSION_ID") or None


def _new_audit_path_within_roots(path: Path, roots: Sequence[Path]) -> Path:
    """Keep the configured leaf unresolved while confining its existing parent."""
    expanded = path.expanduser()
    if not expanded.is_absolute() or not expanded.name:
        raise ValueError("Configured MCP audit log must be an absolute file path.")
    parent = resolve_within_roots(roots, str(expanded.parent), "audit")
    return parent / expanded.name


def create_server(
    skill_roots: Sequence[Path] | None = None,
    detection_registry: Path | None = None,
    workspace_roots: Sequence[Path] | None = None,
    audit_log: Path | None = None,
    audit_roots: Sequence[Path] | None = None,
    audit_shared: bool | None = None,
    audit_session_id: str | None = None,
    project_root: Path | None = None,
    reference_roots: Sequence[Path] | None = None,
) -> FastMCP:
    """Create the MCP agent-operations server with immutable read snapshots.

    Args:
        skill_roots: Optional precedence-ordered roots used instead of environment
            configuration. One immutable catalog snapshot is reused until explicit refresh.
        detection_registry: Optional methodology-owned technology detection registry used
            instead of `MCP_AGENT_OPS_DETECTION_REGISTRY`.
        workspace_roots: Optional allowed roots for repositories, projects, verification
            targets, and worktree destinations supplied through model-facing calls.
        audit_log: Optional evaluator-owned JSON Lines path for digest-only tool-call evidence.
        audit_roots: Optional allowed roots for the audit log, replacing environment configuration.
        audit_shared: Allow inherited MCP server processes to append separate streams to one log.
        audit_session_id: Optional evaluator-generated identity copied into every audit record.
        project_root: Working-directory project context used for automatic skill discovery
            beneath `.agents/skills` and `.codex/skills` and reference discovery beneath
            `.agents` and `.codex/skills`. Defaults to the process working directory and is
            ignored unless it is inside a configured workspace.
        reference_roots: Optional ordered user reference folders used instead of environment
            configuration. Every contained UTF-8 file is available by relative path.

    Returns:
        A FastMCP server ready for in-memory testing or stdio execution.

    Claim tools mutate target Git-global claim state. Hierarchy tools may write HTML and
    durable JSON plans beneath configured workspace roots or Codex's conventional
    visualization subtree. Verification, skill, and reference operations are read-only.
    Catalog and detection snapshots improve reads but never replace disk-authoritative
    claim, skill, or reference state.
    """
    roots = list(skill_roots) if skill_roots is not None else configured_skill_roots()
    configured_references = (
        list(reference_roots)
        if reference_roots is not None
        else configured_reference_roots()
    )
    registry = detection_registry or configured_detection_registry()
    workspaces = (
        list(workspace_roots)
        if workspace_roots is not None
        else configured_workspace_roots()
    )
    hierarchy_roots = _hierarchy_roots(workspaces)
    active_project_root = (project_root or Path.cwd()).expanduser().resolve()
    project_roots = _project_skill_roots(active_project_root, workspaces)
    project_reference_roots = _project_reference_roots(active_project_root, workspaces)
    catalog_roots = [*project_roots, *roots]
    skill_validation_roots = [
        *catalog_roots,
        *([active_project_root] if project_roots else []),
    ]
    configured_log = audit_log if audit_log is not None else configured_audit_log()
    allowed_audit_roots = (
        list(audit_roots) if audit_roots is not None else configured_audit_roots()
    )
    shared_audit = audit_shared if audit_shared is not None else configured_audit_shared()
    configured_session = (
        audit_session_id
        if audit_session_id is not None
        else configured_audit_session_id()
    )
    mcp = FastMCP("MCP Agent Operations")
    tool_audit_log: ToolAuditLog | None = None
    if shared_audit and configured_log is None:
        raise ValueError("Shared MCP audit logging requires an audit log path.")
    if configured_log is not None:
        resolved_audit_log = _new_audit_path_within_roots(
            configured_log,
            allowed_audit_roots,
        )
        tool_audit_log = ToolAuditLog(
            resolved_audit_log,
            shared=shared_audit,
            session_id=configured_session,
        )
    catalog_lock = threading.Lock()
    catalog_snapshot: SkillCatalog | None = None
    reference_lock = threading.Lock()
    reference_snapshot: ReferenceCatalog | None = None
    detection_lock = threading.Lock()
    detection_snapshot: dict[str, object] | None = None

    def build_catalog() -> SkillCatalog:
        try:
            return SkillCatalog.from_roots(
                catalog_roots,
                recursive_roots=project_roots,
            )
        except (OSError, UnicodeError, ValueError, yaml.YAMLError) as error:
            raise ValueError(_skill_catalog_error_message(error, roots)) from None

    def catalog() -> SkillCatalog:
        nonlocal catalog_snapshot
        with catalog_lock:
            if catalog_snapshot is None:
                catalog_snapshot = build_catalog()
            return catalog_snapshot

    def refresh_catalog() -> SkillCatalog:
        nonlocal catalog_snapshot
        replacement = build_catalog()
        with catalog_lock:
            catalog_snapshot = replacement
        return replacement

    def build_references() -> ReferenceCatalog:
        try:
            return ReferenceCatalog.from_scopes(
                project_reference_roots,
                configured_references,
            )
        except (OSError, UnicodeError, ValueError):
            raise ValueError("Configured reference catalog is invalid.") from None

    def references() -> ReferenceCatalog:
        nonlocal reference_snapshot
        with reference_lock:
            if reference_snapshot is None:
                reference_snapshot = build_references()
            return reference_snapshot

    def refresh_references() -> ReferenceCatalog:
        nonlocal reference_snapshot
        replacement = build_references()
        with reference_lock:
            reference_snapshot = replacement
        return replacement

    def workspace_path(value: str) -> Path:
        return resolve_within_roots(workspaces, value, "workspace")

    def hierarchy_path(value: str) -> Path:
        return resolve_within_roots(hierarchy_roots, value, "hierarchy")

    def hierarchy_source(value: object) -> object:
        """Resolve an explicit hierarchy source path without confusing inline JSON or YAML."""
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if (
            not stripped
            or "\n" in value
            or "\r" in value
            or stripped.startswith(("{", "["))
        ):
            return value
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return hierarchy_path(value)
        try:
            is_existing_path = candidate.exists() or candidate.is_symlink()
        except OSError:
            is_existing_path = False
        if is_existing_path:
            raise ValueError(
                "Hierarchy source file paths supplied through MCP must be absolute "
                "within configured workspace roots."
            )
        return value

    def hierarchy_output_folder(value: str | None, *, required: bool) -> Path | None:
        """Resolve an explicit output folder or the server project when a write is required."""
        if value is not None:
            return hierarchy_path(value)
        if required:
            return hierarchy_path(str(active_project_root))
        return None

    def hierarchy_plan_path(value: str) -> Path:
        """Authorize a plan and any valid stored custom-theme path before domain access."""
        plan_path = hierarchy_path(value)
        try:
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return plan_path
        if isinstance(payload, dict):
            themes_folder = payload.get("themesFolder")
            if isinstance(themes_folder, str):
                hierarchy_path(themes_folder)
        return plan_path

    def skill_path(value: str) -> Path:
        return resolve_within_roots(catalog_roots, value, "skill")

    def skill_validation_path(value: str) -> Path:
        """Resolve absolute paths safely and all other values as catalog skill names."""
        if Path(value).expanduser().is_absolute():
            return resolve_within_roots(
                skill_validation_roots,
                value,
                "skill validation",
            )
        return Path(catalog().find_skill(value).path)

    def detection_catalog() -> dict[str, object]:
        nonlocal detection_snapshot
        if registry is None:
            raise ValueError(
                "Technology detection requires MCP_AGENT_OPS_DETECTION_REGISTRY configuration."
            )
        with detection_lock:
            if detection_snapshot is None:
                try:
                    detection_snapshot = load_detection_registry(registry)
                except (OSError, UnicodeError, ValueError, yaml.YAMLError):
                    raise ValueError(
                        "Configured technology detection registry is invalid."
                    ) from None
            return detection_snapshot

    @mcp.tool
    def claim_status(repository: str) -> ClaimCommandResult:
        """Return primary-root claim state or a structured migration stop without creating absent state."""
        return run_claim_command(["--repo", str(workspace_path(repository)), "status"])

    @mcp.tool
    def claim_acquire(
        repository: str,
        claim_id: str,
        agent: str,
        task: str,
        root_task_id: str,
        work_item_id: str | None = None,
        activity: str | None = None,
        files: list[str] | None = None,
        trees: list[str] | None = None,
        resources: list[str] | None = None,
        project_files: _ProjectFilesScope = False,
        backlog: _BacklogScope = False,
        all_files: _AllFilesScope = False,
        scope_reason: _ScopeReason = None,
        parent_claim_id: str | None = None,
        branch: str | None = None,
        worktree_path: str | None = None,
        base: str = "HEAD",
        resource_class: str | None = None,
        resource_id: str | None = None,
        expected_duration_seconds: int | None = None,
        requested_hard_stop_duration_seconds: int | None = None,
        compat_file_directories: bool = False,
    ) -> ClaimCommandResult:
        """Atomically acquire one work item, file domain, or timed resource.

        Work-item scope uses work_item_id with activity work or update. Named resources
        require complete timing evidence resolved against PROJECT.yaml. Project-files
        excludes backlog and supports caller-requested isolation only beneath the primary
        worktree's canonical .worktrees/<claim-id> root, with backlog omitted through
        worktree-specific sparse checkout. Schema-version-2 results preserve the
        package-owned claim engine's current outcomes, rejection fields, and exit codes.
        """
        arguments = [
            "--repo",
            str(workspace_path(repository)),
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
        if parent_claim_id is not None:
            arguments.extend(("--parent-claim-id", parent_claim_id))
        if work_item_id is not None:
            arguments.extend(("--work-item-id", work_item_id))
        if activity is not None:
            arguments.extend(("--activity", activity))
        if branch is not None:
            arguments.extend(("--branch", branch))
        if worktree_path is not None:
            arguments.extend(("--worktree-path", str(workspace_path(worktree_path))))
        _append_scope(
            arguments,
            files,
            trees,
            resources,
            project_files,
            backlog,
            all_files,
            scope_reason,
            compat_file_directories,
        )
        _append_resource_timing(
            arguments,
            resource_class,
            resource_id,
            expected_duration_seconds,
            requested_hard_stop_duration_seconds,
        )
        return run_claim_command(arguments)

    @mcp.tool
    def claim_extend(
        repository: str,
        claim_id: str,
        files: list[str] | None = None,
        trees: list[str] | None = None,
        resources: list[str] | None = None,
        project_files: _ProjectFilesScope = False,
        backlog: _BacklogScope = False,
        all_files: _AllFilesScope = False,
        scope_reason: _ScopeReason = None,
        resource_class: str | None = None,
        resource_id: str | None = None,
        expected_duration_seconds: int | None = None,
        requested_hard_stop_duration_seconds: int | None = None,
        compat_file_directories: bool = False,
    ) -> ClaimCommandResult:
        """Atomically add same-domain scope without weakening existing ownership.

        A work-item claim cannot add operational scope. A named resource extension requires
        complete timing evidence. Primary-only scope from a linked claim returns
        SHARED_CHECKOUT_REQUIRED; invalid mixed scope leaves the registry unchanged.
        """
        arguments = [
            "--repo",
            str(workspace_path(repository)),
            "extend",
            "--claim-id",
            claim_id,
        ]
        _append_scope(
            arguments,
            files,
            trees,
            resources,
            project_files,
            backlog,
            all_files,
            scope_reason,
            compat_file_directories,
        )
        _append_resource_timing(
            arguments,
            resource_class,
            resource_id,
            expected_duration_seconds,
            requested_hard_stop_duration_seconds,
        )
        return run_claim_command(arguments)

    @mcp.tool
    def claim_extend_deadline(
        repository: str,
        claim_id: str,
        requested_hard_stop_duration_seconds: int,
        extension_evidence: str,
    ) -> ClaimCommandResult:
        """Extend one configured resource hard stop with bounded evidence."""
        return run_claim_command([
            "--repo",
            str(workspace_path(repository)),
            "extend-deadline",
            "--claim-id",
            claim_id,
            "--requested-hard-stop-duration-seconds",
            str(requested_hard_stop_duration_seconds),
            "--extension-evidence",
            extension_evidence,
        ])

    @mcp.tool
    def claim_heartbeat(repository: str, claim_id: str) -> ClaimCommandResult:
        """Refresh one active claim heartbeat in the repository-global registry."""
        return run_claim_command(
            ["--repo", str(workspace_path(repository)), "heartbeat", "--claim-id", claim_id]
        )

    @mcp.tool
    def claim_release(
        repository: str,
        claim_id: str,
        disposition: str | None = None,
        blocker_reference: str | None = None,
    ) -> ClaimCommandResult:
        """Release one exact claim, including a disposition for work-item ownership."""
        arguments = [
            "--repo",
            str(workspace_path(repository)),
            "release",
            "--claim-id",
            claim_id,
        ]
        if disposition is not None:
            arguments.extend(("--disposition", disposition))
        if blocker_reference is not None:
            arguments.extend(("--blocker-reference", blocker_reference))
        return run_claim_command(arguments)

    @mcp.tool
    def claim_reset(repository: str) -> ClaimCommandResult:
        """Replace the live registry with an empty claim list under its exact lock."""
        return run_claim_command(["--repo", str(workspace_path(repository)), "reset"])

    @mcp.tool
    def claim_maintain_journal(repository: str, hot_days: int = 2) -> ClaimCommandResult:
        """Archive complete UTC claim-event days while retaining the configured hot window."""
        return run_claim_command(
            [
                "--repo",
                str(workspace_path(repository)),
                "maintain-journal",
                "--hot-days",
                str(hot_days),
            ]
        )

    @mcp.tool
    def claim_report(repository: str, since: str = "2d") -> ClaimCommandResult:
        """Report canonical contention metrics without creating or migrating absent state."""
        return run_claim_command(
            [
                "--repo",
                str(workspace_path(repository)),
                "report",
                "--since",
                since,
                "--format",
                "json",
            ]
        )

    @mcp.tool
    def render_hierarchy_html(
        source: object,
        title: str = "Hierarchy",
        theme: str = "default",
        themes_folder: str | None = None,
        numbering: bool = False,
        checkboxes: bool = False,
        completed_items: list[str] | None = None,
        output_filename: str | None = None,
        output_folder: str | None = None,
    ) -> str:
        """Render safe self-contained hierarchy HTML and optionally save it.

        Inline mappings, sequences, JSON, and YAML require no filesystem access. An
        explicit source path, custom theme folder, or output folder must be absolute and
        resolve beneath the hierarchy roots. When a filename is supplied without an output
        folder, the authorized server project directory is used.

        Args:
            source: Inline mapping, sequence, JSON, YAML, or an absolute JSON/YAML path.
            title: Browser and page title.
            theme: Packaged or custom theme base name without `.css`.
            themes_folder: Absolute folder for a custom theme, or null for packaged themes.
            numbering: Add one-based dotted hierarchy numbers.
            checkboxes: Add read-only completion markers.
            completed_items: Exact dotted paths rendered as complete; requires checkboxes.
            output_filename: Optional base HTML filename without a directory.
            output_folder: Optional absolute destination beneath an authorized hierarchy root.

        Returns:
            Complete HTML when `output_filename` is absent, otherwise the resolved saved
            HTML path.

        Raises:
            ValueError: If a path escapes the hierarchy roots, inputs conflict, or rendering fails.

        Side effects:
            Reads an authorized source or custom theme and writes one HTML file when selected.
        """
        resolved_output_folder = hierarchy_output_folder(
            output_folder,
            required=output_filename is not None,
        )
        result = render_hierarchy_html_domain(
            hierarchy_source(source),
            title=title,
            theme=theme,
            themes_folder=(
                hierarchy_path(themes_folder) if themes_folder is not None else None
            ),
            numbering=numbering,
            checkboxes=checkboxes,
            completed_items=completed_items or [],
            output_filename=output_filename,
            output_folder=resolved_output_folder,
        )
        return str(result)

    @mcp.tool
    def create_hierarchy_plan(
        source: object,
        output_filename: str,
        title: str = "Hierarchy plan",
        theme: str = "default",
        themes_folder: str | None = None,
        output_folder: str | None = None,
        completed_items: list[str] | None = None,
    ) -> str:
        """Create a durable hierarchy JSON plan and its same-named HTML rendering.

        Source, theme, and output paths must be absolute beneath the hierarchy roots. The
        output folder defaults to the authorized server project directory.

        Args:
            source: Inline mapping, sequence, JSON, YAML, or an absolute JSON/YAML path.
            output_filename: Base HTML filename; the JSON plan uses the same base name.
            title: Browser and page title.
            theme: Packaged or custom theme base name without `.css`.
            themes_folder: Absolute folder for a custom theme, or null for packaged themes.
            output_folder: Optional absolute destination beneath an authorized hierarchy root.
            completed_items: Exact dotted paths or unique titles initially marked complete.

        Returns:
            Resolved JSON plan path for later `update_hierarchy_plan` calls.

        Raises:
            ValueError: If a path escapes the hierarchy roots or plan creation fails.

        Side effects:
            Reads an authorized source or theme and writes one JSON file plus one HTML file.
        """
        result = create_hierarchy_plan_domain(
            hierarchy_source(source),
            title=title,
            theme=theme,
            themes_folder=(
                hierarchy_path(themes_folder) if themes_folder is not None else None
            ),
            output_filename=output_filename,
            output_folder=hierarchy_output_folder(output_folder, required=True),
            completed_items=completed_items or [],
        )
        return str(result)

    @mcp.tool
    def update_hierarchy_plan(
        plan_path: str,
        target: str,
        completed: bool | None = None,
        text: str | None = None,
        add_child: str | None = None,
        replace_children: list[str] | None = None,
        add_peer_after: str | None = None,
    ) -> HierarchyPlanUpdateResult:
        """Apply exactly one targeted plan mutation and regenerate its HTML rendering.

        The plan path must be absolute beneath the hierarchy roots. The target is
        an exact dotted hierarchy number or an exact unique title. Supply exactly one of
        `completed`, `text`, `add_child`, `replace_children`, or `add_peer_after`.

        Args:
            plan_path: Absolute JSON plan path returned by `create_hierarchy_plan`.
            target: Exact dotted path or exact unique item title.
            completed: Replacement completion state; branch updates include descendants.
            text: Replacement item text.
            add_child: Text for one appended child.
            replace_children: Ordered replacement child texts; an empty list removes all.
            add_peer_after: Text for one peer inserted immediately after the target.

        Returns:
            Structured success, plan path, automatically completed ancestors, and the
            next incomplete executable leaf with its parent context.

        Raises:
            ValueError: If the path escapes its workspace, the target is invalid, or the
                call supplies other than one mutation.

        Side effects:
            Rewrites one authorized JSON plan and regenerates its same-named HTML report.
        """
        result = update_hierarchy_plan_domain(
            hierarchy_plan_path(plan_path),
            target,
            completed=completed,
            text=text,
            add_child=add_child,
            replace_children=replace_children,
            add_peer_after=add_peer_after,
        )
        return result

    @mcp.tool
    def verify_yaml(repository_root: str, paths: list[str]) -> VerificationReport:
        """Validate exact YAML files, including duplicate keys, with structured diagnostics."""
        return verify_yaml_domain(workspace_path(repository_root), paths)

    @mcp.tool
    def verify_markdown_links(
        repository_root: str,
        patterns: list[str] | None = None,
    ) -> VerificationReport:
        """Verify local Markdown targets and anchors selected by simple root-relative globs."""
        return verify_markdown_links_domain(
            workspace_path(repository_root), patterns or ["**/*.md"]
        )

    @mcp.tool
    def reference_load(names: list[str]) -> ReferenceLoadResult:
        """Load recursive text references aggregated across every matching allowed folder.

        Args:
            names: One to thirty-two unique relative paths in requested result order.

        Returns:
            An ordered all-or-nothing result from the active immutable reference snapshot.
        """
        return references().load(names)

    @mcp.tool
    def reference_refresh() -> PublishedReferenceCatalog:
        """Atomically refresh project and configured user reference scopes."""
        return refresh_references().public_result()

    @mcp.tool
    def skill_list() -> PublishedSkillCatalog:
        """List path-free skill metadata, digests, resources, and shadowing counts."""
        return catalog().public_result()

    @mcp.tool
    def skill_find(name: str) -> FoundSkill:
        """Return the precedence-resolved absolute `SKILL.md` path for one skill name.

        Args:
            name: Exact frontmatter name in the current catalog snapshot.

        Returns:
            The requested name and selected project-overlay or configured-root path.

        Raises:
            SkillNotFoundError: If no configured skill has the requested name.

        The operation is read-only and does not rescan roots until `skill_refresh`.
        """
        return catalog().find_skill(name)

    @mcp.tool
    def skill_read(name: str, include_extensions: bool = False) -> BatchLoadedSkill:
        """Read one precedence-resolved skill and optionally append its extension.

        Args:
            name: Exact catalog name of the required base skill.
            include_extensions: Search for `<name>.extension` through normal catalog
                precedence and append it when present. Defaults to false.

        Returns:
            The base content, optional extension content, aggregate digest, base resources,
            and names of applied extensions without host filesystem paths.
        """
        return catalog().read_model_skill(name, include_extensions=include_extensions)

    @mcp.tool
    def skill_read_resource(name: str, resource_path: str) -> LoadedSkillResource:
        """Read one supporting skill resource without permitting directory traversal."""
        return catalog().read_resource(name, resource_path)

    @mcp.tool
    def skill_load(
        names: list[str],
        include_extensions: bool = False,
    ) -> SkillLoadResult:
        """Load skills and optionally append independently resolved extensions.

        Args:
            names: One to thirty-two unique base skill names in required order.
            include_extensions: Search for each `<name>.extension` through normal catalog
                precedence and append available extensions. Defaults to false.

        Returns:
            An ordered all-or-nothing result. Missing optional extensions are not errors,
            but required base skills and combined content limits remain enforced.
        """
        return catalog().load_skills(names, include_extensions=include_extensions)

    @mcp.tool
    def skill_resource_load(
        requests: list[SkillResourceRequest],
    ) -> SkillResourceLoadResult:
        """Load several supporting resources in one ordered all-or-nothing operation."""
        return catalog().load_resources(requests)

    @mcp.tool
    def skill_refresh() -> PublishedSkillCatalog:
        """Atomically refresh project and configured user skill roots."""
        return refresh_catalog().public_result()

    @mcp.tool
    def skill_validate(paths: list[str]) -> SkillValidationResult:
        """Validate catalog names or explicit skill paths beneath the working project.

        Args:
            paths: One or more catalog names or absolute paths within configured skill roots
                or the authorized working project. Names use the same precedence-selected
                snapshot as `skill_find`.

        Returns:
            A read-only validation result containing safe root-relative findings.

        Raises:
            ValueError: If no inputs are supplied, a name is unknown, or a path escapes
                the configured skill roots and authorized working project.
        """
        return validate_skills(
            [skill_validation_path(path) for path in paths],
            allowed_roots=skill_validation_roots,
        )

    @mcp.tool
    def detect_technology_skills(project_root: str, scopes: list[str]) -> TechnologyDetectionResult:
        """Detect required technology skills for project scopes using the configured registry."""
        if registry is None:
            raise ValueError(
                "Technology detection requires MCP_AGENT_OPS_DETECTION_REGISTRY configuration."
            )
        current_catalog = catalog().public_result()
        skills_root = catalog_roots[0] if catalog_roots else registry.parent
        detected = detect_domain(
            workspace_path(project_root),
            scopes,
            registry,
            skills_root,
            [entry.name for entry in current_catalog.skills],
            registry_data=detection_catalog(),
        )
        public_result = detected.model_copy(deep=True)
        public_result.result["projectRoot"] = "."
        runtime_catalog = public_result.result.get("runtimeSkillCatalog")
        if isinstance(runtime_catalog, dict):
            runtime_catalog.pop("skillsRoot", None)
            runtime_catalog["catalogRevision"] = current_catalog.revision
        return public_result

    @mcp.resource("skill://catalog", mime_type="application/json")
    def skill_catalog_resource() -> str:
        """Return the current structured skill catalog as JSON."""
        return catalog().public_result().model_dump_json()

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

    if tool_audit_log is not None:
        mcp.add_middleware(
            ToolAuditMiddleware(tool_audit_log, AUDITED_TOOL_NAMES)
        )

    return mcp


def run_server() -> None:
    """Run the configured MCP agent-operations server over stdio until its host disconnects."""
    create_server().run(transport="stdio", show_banner=False)
