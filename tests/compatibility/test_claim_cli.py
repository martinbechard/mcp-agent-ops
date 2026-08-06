# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies claim command, migration, lifecycle, reporting, and cross-process lock compatibility.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

CLAIM_MODULE = "mcp_agent_ops.adapters.cli.claims"
AUTHORITY_CLAIM_SCRIPT = os.environ.get("MCP_AGENT_OPS_AUTHORITY_CLAIM_SCRIPT")
RESOURCE_CLASSES = (
    "backlog-mutation",
    "main-integration",
    "browser-server",
    "database-port",
    "live-model-evaluation",
)

_STALE_LEGACY_LOCK_CHILD = r"""
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from mcp_agent_ops.claims import engine, service

repository = Path(sys.argv[1])
legacy_registry = Path(sys.argv[2]).resolve()
ready_path = Path(sys.argv[3])
resume_path = Path(sys.argv[4])
result_path = Path(sys.argv[5])
operation = sys.argv[6]
original_exclusive_text_file = engine.exclusive_text_file
paused = False


@contextmanager
def pause_first_legacy_lock(path, *, create=True):
    global paused
    if not paused and path.resolve() == legacy_registry:
        paused = True
        descriptor = os.open(path, os.O_RDWR)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as locked_file:
            ready_path.write_text("ready\n", encoding="utf-8")
            deadline = time.monotonic() + 10
            while not resume_path.exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("parent did not complete legacy-marker handoff")
                time.sleep(0.01)
            engine.portalocker.lock(locked_file, engine.portalocker.LOCK_EX)
            try:
                yield locked_file
            finally:
                engine.portalocker.unlock(locked_file)
        return
    with original_exclusive_text_file(path, create=create) as locked_file:
        yield locked_file


engine.exclusive_text_file = pause_first_legacy_lock
arguments = ["--repo", str(repository), operation]
if operation == "release":
    arguments.extend(["--claim-id", "legacy-live"])
command_result = service.run_claim_command(arguments)
result_path.write_text(
    json.dumps({
        "exit_code": command_result.exit_code,
        "result": command_result.result,
    }),
    encoding="utf-8",
)
"""


class AgentClaimTests(unittest.TestCase):
    """Exercise the public claim CLI against temporary Git repositories."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.repository.mkdir()
        (self.repository / "src").mkdir()
        (self.repository / "backlog").mkdir()
        (self.repository / ".gitignore").write_text(
            "/.worktrees/\n/.codex/agent-claim/\n",
            encoding="utf-8",
        )
        (self.repository / "README.md").write_text("baseline\n", encoding="utf-8")
        (self.repository / "src" / "one.py").write_text("one\n", encoding="utf-8")
        (self.repository / "backlog" / "item.md").write_text("queued\n", encoding="utf-8")
        self.write_deadline_policy()
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Claim Test")
        self.git("add", ".")
        self.git("commit", "-m", "baseline")

    def write_deadline_policy(self) -> None:
        """Write the exact configured resource-class policy required by claim acquisition."""
        class_entries = "\n".join(
            f"      {class_id}:\n"
            "        maximum_duration_seconds: 3600\n"
            "        cleanup_grace_seconds: 120"
            for class_id in RESOURCE_CLASSES
        )
        (self.repository / "PROJECT.yaml").write_text(
            "resource_coordination:\n"
            "  selected: agent-claim\n"
            "  deadline_policy:\n"
            "    resource_classes:\n"
            f"{class_entries}\n"
            "    resource_overrides: {}\n",
            encoding="utf-8",
        )

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run Git in the temporary repository and require success."""
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            text=True,
            capture_output=True,
        )

    def claim(
        self,
        *arguments: str,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the bundled claim command with optional deterministic environment values."""
        command_environment = os.environ.copy()
        command_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command_environment.update(environment or {})
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                CLAIM_MODULE,
                "--repo",
                str(self.repository),
                *arguments,
            ],
            check=False,
            text=True,
            capture_output=True,
            env=command_environment,
        )
        if completed.returncode == 3:
            print(f"claim coordination result: {completed.stdout}")
        return completed

    def authority_claim(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        """Run the explicitly configured source-authority helper for cross-implementation checks."""
        if AUTHORITY_CLAIM_SCRIPT is None:
            raise AssertionError("MCP_AGENT_OPS_AUTHORITY_CLAIM_SCRIPT is not configured")
        return subprocess.run(
            [
                sys.executable,
                AUTHORITY_CLAIM_SCRIPT,
                "--repo",
                str(self.repository),
                *arguments,
            ],
            check=False,
            text=True,
            capture_output=True,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def output(self, completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
        """Decode one structured command result."""
        return json.loads(completed.stdout)

    def acquire_arguments(self, claim_id: str) -> list[str]:
        """Build common acquisition arguments for one claim."""
        return [
            "acquire",
            "--claim-id",
            claim_id,
            "--agent",
            claim_id,
            "--task",
            f"task {claim_id}",
            "--root-task-id",
            claim_id,
        ]

    def work_item_arguments(
        self,
        claim_id: str,
        work_item_id: str,
        activity: str = "work",
    ) -> list[str]:
        """Build one exact work-item acquisition."""
        return [
            *self.acquire_arguments(claim_id),
            "--work-item-id",
            work_item_id,
            "--activity",
            activity,
        ]

    def timed_resource_arguments(self) -> list[str]:
        """Build one valid resource claim with complete timing evidence."""
        return [
            "--resource",
            "browser-test:primary",
            "--resource-class",
            "browser-server",
            "--resource-id",
            "browser-test:primary",
            "--expected-duration-seconds",
            "300",
            "--requested-hard-stop-duration-seconds",
            "600",
        ]

    def state_root(self) -> Path:
        """Return the canonical primary-worktree claim-state root."""
        return self.repository / ".codex" / "agent-claim"

    def registry_path(self) -> Path:
        """Return the canonical live registry path."""
        return self.state_root() / "agent-claims.json"

    def state_marker_path(self) -> Path:
        """Return the canonical migration-state marker path."""
        return self.state_root() / "state.json"

    def legacy_registry_path(self) -> Path:
        """Return the pre-migration registry path."""
        return self.repository / ".git" / "agent-claims.json"

    def legacy_event_root(self) -> Path:
        """Return the pre-migration event-history path."""
        return self.repository / ".git" / "agent-claim-events"

    def hot_directory(self) -> Path:
        """Return the canonical hot-journal directory."""
        return self.state_root() / "agent-claim-events" / "hot"

    def run_stale_legacy_lock_process(self, operation: str) -> dict[str, object]:
        """Pause a real process at its first legacy lock and complete the state handoff."""
        self.legacy_registry_path().write_text(
            json.dumps({
                "claims": [{
                    "claim_id": "legacy-live",
                    "agent": "legacy-agent",
                    "root_task_id": "legacy-root",
                    "task": "legacy claim",
                    "files": ["README.md"],
                    "trees": [],
                    "resources": [],
                    "claimed_at": "2026-08-05T10:00:00Z",
                    "heartbeat": "2026-08-05T10:00:00Z",
                }]
            }) + "\n",
            encoding="utf-8",
        )
        coordination_root = Path(self.temporary_directory.name) / "coordination"
        coordination_root.mkdir()
        ready_path = coordination_root / "ready"
        resume_path = coordination_root / "resume"
        result_path = coordination_root / "result.json"
        source_root = Path(__file__).resolve().parents[2] / "src"
        child_environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        child_environment["PYTHONPATH"] = os.pathsep.join(
            filter(None, [str(source_root), child_environment.get("PYTHONPATH")])
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _STALE_LEGACY_LOCK_CHILD,
                str(self.repository),
                str(self.legacy_registry_path()),
                str(ready_path),
                str(resume_path),
                str(result_path),
                operation,
            ],
            cwd=self.repository,
            env=child_environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 10
        while not ready_path.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                result = result_path.read_text(encoding="utf-8") if result_path.exists() else ""
                self.fail(
                    f"stale-lock child exited before ready: {stdout}\n{stderr}\n{result}"
                )
            if time.monotonic() >= deadline:
                self.fail("stale-lock child did not open the legacy descriptor")
            time.sleep(0.01)

        drained = self.claim("release", "--claim-id", "legacy-live")
        migrated = self.claim(
            *self.acquire_arguments("canonical-owner"),
            "--file",
            "README.md",
        )
        resume_path.write_text("resume\n", encoding="utf-8")
        stdout, stderr = process.communicate(timeout=10)

        self.assertEqual(0, drained.returncode, drained.stderr)
        self.assertEqual("RELEASED", self.output(drained)["outcome"])
        self.assertEqual(0, migrated.returncode, migrated.stderr)
        self.assertEqual("SHARED_CHECKOUT_ACQUIRED", self.output(migrated)["outcome"])
        self.assertEqual(0, process.returncode, f"{stdout}\n{stderr}")
        self.assertEqual(
            {
                "migration_status": "complete",
                "origin": "legacy",
                "schema_version": 1,
                "state_layout_version": 2,
            },
            json.loads(self.state_marker_path().read_text(encoding="utf-8")),
        )
        return json.loads(result_path.read_text(encoding="utf-8"))

    def test_status_is_read_only_when_all_state_is_absent(self) -> None:
        completed = self.claim("status")

        self.assertEqual(0, completed.returncode, completed.stderr)
        result = self.output(completed)
        self.assertEqual("STATUS", result["outcome"])
        self.assertEqual(str(self.registry_path().resolve()), result["registry"])
        self.assertEqual([], result["claims"])
        self.assertFalse(self.state_root().exists())
        self.assertFalse(self.legacy_registry_path().exists())
        self.assertFalse(self.legacy_event_root().exists())

    def test_first_mutation_writes_exact_fresh_state_contract(self) -> None:
        acquired = self.claim(*self.acquire_arguments("fresh"), "--file", "README.md")

        self.assertEqual(0, acquired.returncode, acquired.stderr)
        self.assertEqual(
            {
                "schema_version": 1,
                "state_layout_version": 2,
                "migration_status": "complete",
                "origin": "fresh",
            },
            json.loads(self.state_marker_path().read_text(encoding="utf-8")),
        )
        self.assertFalse(self.legacy_registry_path().exists())
        self.assertFalse(self.legacy_event_root().exists())

    def test_empty_legacy_state_migrates_to_exact_cross_implementation_markers(self) -> None:
        self.legacy_registry_path().write_text('{"claims": []}\n', encoding="utf-8")
        legacy_hot = self.legacy_event_root() / "hot"
        legacy_hot.mkdir(parents=True)
        (legacy_hot / "2026-08-05.jsonl").write_text("", encoding="utf-8")

        acquired = self.claim(*self.acquire_arguments("migrated"), "--file", "README.md")

        self.assertEqual(0, acquired.returncode, acquired.stderr)
        self.assertEqual(
            {
                "schema_version": 1,
                "state_layout_version": 2,
                "migration_status": "complete",
                "origin": "legacy",
            },
            json.loads(self.state_marker_path().read_text(encoding="utf-8")),
        )
        self.assertTrue(self.legacy_registry_path().is_dir())
        self.assertEqual(
            {
                "schema_version": 1,
                "state_layout_version": 2,
                "migrated": "registry",
            },
            json.loads(
                (self.legacy_registry_path() / "state.json").read_text(encoding="utf-8")
            ),
        )
        self.assertTrue(self.legacy_event_root().is_file())
        self.assertEqual(
            {
                "schema_version": 1,
                "state_layout_version": 2,
                "migrated": "events",
            },
            json.loads(self.legacy_event_root().read_text(encoding="utf-8")),
        )
        status = self.claim("status")
        self.assertEqual(0, status.returncode, status.stderr)
        self.assertEqual(["migrated"], [claim["claim_id"] for claim in self.output(status)["claims"]])

    def test_command_helper_marker_fixture_is_accepted_without_rewrite(self) -> None:
        self.state_root().mkdir(parents=True)
        self.registry_path().write_text('{"claims": []}\n', encoding="utf-8")
        self.state_marker_path().write_text(
            json.dumps({
                "schema_version": 1,
                "state_layout_version": 2,
                "migration_status": "complete",
                "origin": "legacy",
            }) + "\n",
            encoding="utf-8",
        )
        self.legacy_registry_path().mkdir()
        (self.legacy_registry_path() / "state.json").write_text(
            json.dumps({
                "schema_version": 1,
                "state_layout_version": 2,
                "migrated": "registry",
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.legacy_event_root().write_text(
            json.dumps({
                "schema_version": 1,
                "state_layout_version": 2,
                "migrated": "events",
            }, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        before = {
            path: path.read_bytes()
            for path in (
                self.registry_path(),
                self.state_marker_path(),
                self.legacy_registry_path() / "state.json",
                self.legacy_event_root(),
            )
        }

        status = self.claim("status")

        self.assertEqual(0, status.returncode, status.stderr)
        self.assertEqual("STATUS", self.output(status)["outcome"])
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    @unittest.skipUnless(
        AUTHORITY_CLAIM_SCRIPT is not None
        and Path(AUTHORITY_CLAIM_SCRIPT).is_file(),
        "source-authority helper is not configured",
    )
    def test_external_and_source_authority_share_live_state_bidirectionally(self) -> None:
        external_acquire = self.claim(
            *self.acquire_arguments("external-owner"),
            "--file",
            "README.md",
        )
        authority_status = self.authority_claim("status")
        authority_release = self.authority_claim(
            "release",
            "--claim-id",
            "external-owner",
        )
        authority_acquire = self.authority_claim(
            *self.work_item_arguments("authority-owner", "provider#cross", "update")
        )
        external_status = self.claim("status")

        self.assertEqual(0, external_acquire.returncode, external_acquire.stderr)
        self.assertEqual(0, authority_status.returncode, authority_status.stderr)
        self.assertEqual(
            ["external-owner"],
            [claim["claim_id"] for claim in self.output(authority_status)["claims"]],
        )
        self.assertEqual(0, authority_release.returncode, authority_release.stderr)
        self.assertEqual(0, authority_acquire.returncode, authority_acquire.stderr)
        claims = self.output(external_status)["claims"]
        self.assertEqual(["authority-owner"], [claim["claim_id"] for claim in claims])
        self.assertEqual("provider#cross", claims[0]["work_item_id"])
        self.assertEqual("update", claims[0]["activity"])

    def test_canonical_and_any_legacy_registry_are_a_non_mutating_split_state(self) -> None:
        self.registry_path().parent.mkdir(parents=True)
        self.registry_path().write_text(
            json.dumps({"claims": [{"claim_id": "canonical-live"}]}) + "\n",
            encoding="utf-8",
        )
        self.legacy_registry_path().write_text('{"claims": []}\n', encoding="utf-8")
        canonical_before = self.registry_path().read_bytes()
        legacy_before = self.legacy_registry_path().read_bytes()

        completed = self.claim("status")

        self.assertEqual(3, completed.returncode)
        result = self.output(completed)
        self.assertEqual("CLAIM_STATE_MIGRATION_BLOCKED", result["outcome"])
        self.assertEqual("contradictory_dual_state", result["reason"])
        self.assertEqual(canonical_before, self.registry_path().read_bytes())
        self.assertEqual(legacy_before, self.legacy_registry_path().read_bytes())

    def test_live_legacy_registry_is_drain_only_until_exact_release(self) -> None:
        self.legacy_registry_path().write_text(
            json.dumps({
                "claims": [{
                    "claim_id": "legacy-live",
                    "agent": "legacy-agent",
                    "root_task_id": "legacy-root",
                    "task": "legacy claim",
                    "files": ["README.md"],
                    "trees": [],
                    "resources": [],
                    "claimed_at": "2026-08-05T10:00:00Z",
                    "heartbeat": "2026-08-05T10:00:00Z",
                }]
            }) + "\n",
            encoding="utf-8",
        )

        blocked = self.claim(*self.acquire_arguments("new"), "--file", "src/one.py")
        self.assertEqual(3, blocked.returncode)
        self.assertEqual("live_legacy_claims_require_drain", self.output(blocked)["reason"])
        released = self.claim("release", "--claim-id", "legacy-live")
        self.assertEqual(0, released.returncode, released.stderr)
        self.assertEqual("RELEASED", self.output(released)["outcome"])
        self.assertEqual([], json.loads(self.legacy_registry_path().read_text(encoding="utf-8"))["claims"])

        migrated = self.claim(*self.acquire_arguments("new"), "--file", "src/one.py")
        self.assertEqual(0, migrated.returncode, migrated.stderr)
        self.assertTrue(self.legacy_registry_path().is_dir())
        self.assertTrue(self.legacy_event_root().is_file())

    @unittest.skipIf(
        os.name == "nt",
        "Windows does not preserve an open descriptor after path replacement.",
    )
    def test_first_mutating_legacy_lock_re_resolves_across_processes(self) -> None:
        stale = self.run_stale_legacy_lock_process("release")

        self.assertEqual(1, stale["exit_code"])
        self.assertEqual("CLAIM_NOT_FOUND", stale["result"]["outcome"])
        status = self.claim("status")
        self.assertEqual(
            ["canonical-owner"],
            [claim["claim_id"] for claim in self.output(status)["claims"]],
        )

    @unittest.skipIf(
        os.name == "nt",
        "Windows does not preserve an open descriptor after path replacement.",
    )
    def test_first_read_only_legacy_lock_re_resolves_across_processes(self) -> None:
        stale = self.run_stale_legacy_lock_process("status")

        self.assertEqual(0, stale["exit_code"])
        self.assertEqual("STATUS", stale["result"]["outcome"])
        self.assertEqual(
            ["canonical-owner"],
            [claim["claim_id"] for claim in stale["result"]["claims"]],
        )

    def test_work_item_lifecycle_and_report_preserve_current_fields(self) -> None:
        acquired = self.claim(
            *self.work_item_arguments("provider-update", "provider#17", "update"),
            environment={"AGENT_CLAIM_TEST_NOW": "2026-08-05T10:00:00Z"},
        )
        status = self.claim("status")
        released = self.claim(
            "release",
            "--claim-id",
            "provider-update",
            "--disposition",
            "blocked",
            "--blocker-reference",
            "dependency-456",
            environment={"AGENT_CLAIM_TEST_NOW": "2026-08-05T10:05:00Z"},
        )
        report = self.claim(
            "report",
            "--since",
            "1d",
            environment={"AGENT_CLAIM_TEST_NOW": "2026-08-05T12:00:00Z"},
        )

        self.assertEqual(0, acquired.returncode, acquired.stderr)
        claim = self.output(status)["claims"][0]
        self.assertEqual("provider#17", claim["work_item_id"])
        self.assertEqual("update", claim["activity"])
        self.assertEqual("SHARED_CHECKOUT_ACQUIRED", claim["acquisition_outcome"])
        self.assertIn("incarnation_id", claim)
        release_result = self.output(released)
        self.assertEqual("blocked", release_result["disposition"])
        self.assertEqual("dependency-456", release_result["blocker_reference"])
        work_items = self.output(report)["work_items"]
        self.assertEqual(1, work_items["schema_version"])
        segment = work_items["items"][0]["segments"][0]
        self.assertEqual("provider#17", work_items["items"][0]["work_item_id"])
        self.assertEqual("blocked", segment["disposition"])
        self.assertEqual("dependency-456", segment["blocker_reference"])
        self.assertEqual(300.0, segment["duration_seconds"])

    def test_invalid_work_item_release_preserves_registry_bytes(self) -> None:
        acquired = self.claim(*self.work_item_arguments("item", "provider#18"))
        self.assertEqual(0, acquired.returncode, acquired.stderr)
        before = self.registry_path().read_bytes()

        rejected = self.claim("release", "--claim-id", "item")

        self.assertEqual(1, rejected.returncode)
        result = self.output(rejected)
        self.assertEqual("INVALID_WORK_ITEM_RELEASE", result["outcome"])
        self.assertEqual("disposition_required", result["rejection"]["reason"])
        self.assertEqual(before, self.registry_path().read_bytes())

    def test_resource_deadline_extension_uses_configured_policy(self) -> None:
        acquired = self.claim(
            *self.acquire_arguments("browser"),
            *self.timed_resource_arguments(),
            environment={"AGENT_CLAIM_TEST_NOW": "2026-08-05T10:00:00Z"},
        )
        extended = self.claim(
            "extend-deadline",
            "--claim-id",
            "browser",
            "--requested-hard-stop-duration-seconds",
            "900",
            "--extension-evidence",
            "one focused compatibility case remains",
            environment={"AGENT_CLAIM_TEST_NOW": "2026-08-05T10:04:00Z"},
        )

        self.assertEqual(0, acquired.returncode, acquired.stderr)
        deadline = self.output(acquired)["claim"]["deadline"]
        self.assertEqual(3600, deadline["configured_maximum_duration_seconds"])
        self.assertEqual("2026-08-05T10:10:00.000000Z", deadline["hard_stop_at"])
        self.assertEqual(0, extended.returncode, extended.stderr)
        result = self.output(extended)
        self.assertEqual("DEADLINE_EXTENDED", result["outcome"])
        self.assertEqual(900, result["claim"]["deadline"]["requested_hard_stop_duration_seconds"])
        self.assertEqual("2026-08-05T10:15:00.000000Z", result["claim"]["deadline"]["hard_stop_at"])

    def test_reset_replaces_malformed_registry_under_the_same_inode(self) -> None:
        first = self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        self.assertEqual(0, first.returncode, first.stderr)
        inode = self.registry_path().stat().st_ino
        self.registry_path().write_text('{"claims":[', encoding="utf-8")

        reset = self.claim("reset")

        self.assertEqual(0, reset.returncode, reset.stderr)
        self.assertEqual("RESET", self.output(reset)["outcome"])
        self.assertEqual({"claims": []}, json.loads(self.registry_path().read_text(encoding="utf-8")))
        self.assertEqual(inode, self.registry_path().stat().st_ino)

    def test_report_reads_legacy_history_before_empty_migration(self) -> None:
        self.legacy_registry_path().write_text('{"claims": []}\n', encoding="utf-8")
        legacy_hot = self.legacy_event_root() / "hot"
        legacy_hot.mkdir(parents=True)
        event = {
            "schema_version": 1,
            "event_id": "legacy-history-event",
            "timestamp": "2026-08-05T10:00:00.000000Z",
            "action": "acquire",
            "outcome": "PRIMARY",
            "claim_id": "legacy-history",
            "journal_warnings": [],
        }
        (legacy_hot / "2026-08-05.jsonl").write_text(
            json.dumps(event, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        report = self.claim(
            "report",
            "--since",
            "1d",
            environment={"AGENT_CLAIM_TEST_NOW": "2026-08-05T12:00:00Z"},
        )

        self.assertEqual(0, report.returncode, report.stderr)
        result = self.output(report)
        self.assertEqual(1, result["event_count"])
        self.assertEqual(1, result["metrics"]["successful_acquisitions"]["primary"])
        self.assertFalse(self.state_root().exists())
        self.assertTrue(self.legacy_registry_path().is_file())
        self.assertTrue(self.legacy_event_root().is_dir())


if __name__ == "__main__":
    unittest.main()
