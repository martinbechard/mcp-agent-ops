# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Writes evaluator-controlled digest-only evidence for MCP tool calls.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import BinaryIO

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams

try:
    import fcntl
except ImportError:  # pragma: no cover - shared evaluation audit is POSIX-only.
    fcntl = None  # type: ignore[assignment]


def _digest(value: object) -> str:
    """Return a stable digest without retaining the serialized value."""

    def normalize(item: object) -> object:
        if hasattr(item, "model_dump"):
            return normalize(item.model_dump(mode="json"))
        if is_dataclass(item) and not isinstance(item, type):
            return normalize(asdict(item))
        if isinstance(item, Mapping):
            return {str(key): normalize(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [normalize(child) for child in item]
        if item is None or isinstance(item, (str, int, float, bool)):
            return item
        return repr(item)

    encoded = json.dumps(
        normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ToolAuditLog:
    """Own one JSON Lines audit stream for one MCP server process.

    Records contain only tool identity, lifecycle status, sequence numbers, and content
    digests. Shared version-two records also contain evaluator session, random process
    stream, and bounded canonical outcome identifiers. The caller must prevalidate the
    path against an administrator-owned root.
    """

    def __init__(
        self,
        path: Path,
        *,
        shared: bool = False,
        session_id: str | None = None,
    ) -> None:
        self.path = path
        self.shared = shared
        self.stream_id = secrets.token_hex(16) if shared else None
        if session_id is not None and not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise ValueError("MCP audit session identity must be 32 lowercase hexadecimal characters.")
        if shared and session_id is None:
            raise ValueError("Shared MCP audit logging requires a session identity.")
        if not shared and session_id is not None:
            raise ValueError("MCP audit session identity is valid only for shared audit logging.")
        self.session_id = session_id
        self._lock = threading.Lock()
        self._sequence = 0
        if not path.parent.is_dir():
            raise ValueError("Configured MCP audit log parent does not exist.")
        if shared and fcntl is None:
            raise ValueError("Shared MCP audit logging requires POSIX file locking.")
        flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if not shared:
            flags |= os.O_EXCL
        elif hasattr(os, "O_NONBLOCK"):
            flags |= os.O_NONBLOCK
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as error:
            raise ValueError("Configured MCP audit log must be a new regular file.") from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("Configured MCP audit log must be a new regular file.")
            if shared and (
                metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise ValueError(
                    "Shared MCP audit log must be owner-only and owned by this process user."
                )
            self._stream: BinaryIO = os.fdopen(descriptor, "wb", buffering=0)
        except Exception:
            os.close(descriptor)
            raise

    def start(self, tool: str, arguments: object) -> str:
        """Record a started tool call and return its process-local call identifier."""
        with self._lock:
            call_id = str(self._sequence + 1)
            self._append_locked({
                "callId": call_id,
                "tool": tool,
                "status": "started",
                "argumentsDigest": _digest(arguments),
            })
            return call_id

    def finish(
        self,
        call_id: str,
        tool: str,
        status: str,
        result: object,
        outcome: str | None = None,
    ) -> None:
        """Record completion or failure for one previously started tool call."""
        with self._lock:
            fields: dict[str, object] = {
                "callId": call_id,
                "tool": tool,
                "status": status,
                "resultDigest": _digest(result),
            }
            if outcome is not None:
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", outcome):
                    raise ValueError("MCP audit outcomes must be canonical uppercase identifiers.")
                fields["outcome"] = outcome
            self._append_locked(fields)

    def _append_locked(self, fields: dict[str, object]) -> None:
        self._sequence += 1
        record = {
            "schema": "mcp-agent-ops-tool-audit",
            "version": 2 if self.shared else 1,
            "sequence": self._sequence,
            **fields,
        }
        if self.stream_id is not None:
            record["streamId"] = self.stream_id
        if self.session_id is not None:
            record["sessionId"] = self.session_id
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if self.shared:
            assert fcntl is not None
            fcntl.flock(self._stream.fileno(), fcntl.LOCK_EX)
        try:
            remaining = memoryview(encoded)
            while remaining:
                written = self._stream.write(remaining)
                if written is None or written <= 0:
                    raise OSError("Unable to write MCP audit evidence.")
                remaining = remaining[written:]
            os.fsync(self._stream.fileno())
        finally:
            if self.shared:
                assert fcntl is not None
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)


class ToolAuditMiddleware(Middleware):
    """Record digest-only lifecycle evidence around every MCP tool call."""

    def __init__(self, audit_log: ToolAuditLog, allowed_tools: frozenset[str]) -> None:
        self.audit_log = audit_log
        self.allowed_tools = allowed_tools

    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        """Write started and terminal records while preserving the tool result or failure."""
        requested_tool = context.message.name
        tool = requested_tool if requested_tool in self.allowed_tools else "unknown_tool"
        call_id = self.audit_log.start(tool, context.message.arguments or {})
        try:
            result = await call_next(context)
        except Exception as error:
            with suppress(Exception):
                self.audit_log.finish(
                    call_id,
                    tool,
                    "failed",
                    {"errorType": type(error).__name__},
                    "ERROR" if self.audit_log.shared else None,
                )
            raise
        # A post-call audit failure must not turn a completed mutation into a retryable tool failure.
        with suppress(Exception):
            self.audit_log.finish(
                call_id,
                tool,
                "completed",
                result,
                _safe_outcome(tool, result) if self.audit_log.shared else None,
            )
        return result


def _safe_outcome(tool: str, result: ToolResult) -> str | None:
    """Extract one bounded non-content outcome for deterministic evaluation checks."""
    structured = result.structured_content
    if not isinstance(structured, Mapping):
        return None
    if tool.startswith("claim_"):
        claim_result = structured.get("result")
        outcome = claim_result.get("outcome") if isinstance(claim_result, Mapping) else None
        return str(outcome) if isinstance(outcome, str) else None
    if tool in {"verify_yaml", "verify_markdown_links"}:
        ok = structured.get("ok")
        checked_files = structured.get("checked_files")
        if ok is True and isinstance(checked_files, list) and not checked_files:
            return "EMPTY"
        return "OK" if ok is True else "FINDINGS" if ok is False else None
    if tool == "skill_list":
        skills = structured.get("skills")
        if isinstance(skills, list):
            return "CATALOG" if skills else "EMPTY"
        return None
    if tool == "detect_technology_skills":
        detection = structured.get("result")
        if not isinstance(detection, Mapping):
            return None
        loadouts = detection.get("loadouts")
        statuses = {
            str(item.get("status"))
            for item in loadouts
            if isinstance(item, Mapping) and isinstance(item.get("status"), str)
        } if isinstance(loadouts, list) else set()
        if not statuses:
            return "EMPTY"
        if "BLOCKED" in statuses:
            return "BLOCKED"
        if statuses and statuses == {"NO_VARIANT"}:
            return "NO_VARIANT"
        if statuses:
            return "READY"
    return None
