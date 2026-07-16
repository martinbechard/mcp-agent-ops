# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Writes evaluator-controlled digest-only evidence for MCP tool calls.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import hashlib
import json
import os
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
    """Own one exclusive JSON Lines audit file for a single MCP server process.

    Records contain only tool identity, lifecycle status, sequence numbers, and content
    digests. The caller must prevalidate the path against an administrator-owned root.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._sequence = 0
        if not path.parent.is_dir():
            raise ValueError("Configured MCP audit log parent does not exist.")
        flags = os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as error:
            raise ValueError("Configured MCP audit log must be a new regular file.") from error
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Configured MCP audit log must be a new regular file.")
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
    ) -> None:
        """Record completion or failure for one previously started tool call."""
        with self._lock:
            self._append_locked({
                "callId": call_id,
                "tool": tool,
                "status": status,
                "resultDigest": _digest(result),
            })

    def _append_locked(self, fields: dict[str, object]) -> None:
        self._sequence += 1
        record = {
            "schema": "mcp-agent-ops-tool-audit",
            "version": 1,
            "sequence": self._sequence,
            **fields,
        }
        encoded = (
            json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        remaining = memoryview(encoded)
        while remaining:
            written = self._stream.write(remaining)
            if written is None or written <= 0:
                raise OSError("Unable to write MCP audit evidence.")
            remaining = remaining[written:]
        os.fsync(self._stream.fileno())


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
                )
            raise
        # A post-call audit failure must not turn a completed mutation into a retryable tool failure.
        with suppress(Exception):
            self.audit_log.finish(call_id, tool, "completed", result)
        return result
