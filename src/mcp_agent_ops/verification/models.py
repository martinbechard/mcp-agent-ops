# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Defines structured verification findings and reports shared by all adapters.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pydantic import BaseModel, Field


class VerificationFinding(BaseModel):
    """Describe one actionable verification failure.

    Callers use the stable code for control flow and the message for display. Path is
    relative to the inspected root when possible; line and column are one-based.
    """

    code: str
    message: str
    path: str
    line: int | None = None
    column: int | None = None
    target: str | None = None


class VerificationReport(BaseModel):
    """Return the complete read-only result of one verification operation.

    `ok` is true only when every requested input was accessible and no finding was
    produced. `checked_files` lists the files that were actually inspected.
    """

    ok: bool
    checked_files: list[str] = Field(default_factory=list)
    findings: list[VerificationFinding] = Field(default_factory=list)
