# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies copied claim coordination, journaling, reporting, isolation, recovery, and release compatibility.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


CLAIM_MODULE = "mcp_agent_ops.adapters.cli.claims"


class AgentClaimTests(unittest.TestCase):
    """Exercises the public claim command against temporary linked Git worktrees."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repository = Path(self.temporary_directory.name) / "repository"
        self.repository.mkdir()
        (self.repository / "src").mkdir()
        (self.repository / "docs").mkdir()
        (self.repository / "README.md").write_text("baseline\n", encoding="utf-8")
        (self.repository / "src" / "one.py").write_text("one\n", encoding="utf-8")
        (self.repository / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Claim Test")
        self.git("add", ".")
        self.git("commit", "-m", "baseline")

    def git(self, *arguments: str, worktree: Path | None = None) -> subprocess.CompletedProcess[str]:
        """Run Git in the requested temporary worktree and require success."""
        return subprocess.run(
            ["git", "-C", str(worktree or self.repository), *arguments],
            check=True,
            text=True,
            capture_output=True,
        )

    def claim(
        self,
        *arguments: str,
        repo: Path | None = None,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the bundled command with optional deterministic-clock and fault-injection variables."""
        command_environment = os.environ.copy()
        command_environment["PYTHONDONTWRITEBYTECODE"] = "1"
        command_environment.update(environment or {})
        return subprocess.run(
            [sys.executable, "-m", CLAIM_MODULE, "--repo", str(repo or self.repository), *arguments],
            check=False,
            text=True,
            capture_output=True,
            env=command_environment,
        )

    def claim_command(self, *arguments: str, repo: Path | None = None) -> list[str]:
        """Build a subprocess command for concurrency tests without executing it."""
        return [sys.executable, "-m", CLAIM_MODULE, "--repo", str(repo or self.repository), *arguments]

    def acquire_arguments(self, claim_id: str) -> list[str]:
        """Build the common acquisition arguments for one independent test task."""
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

    def isolated_arguments(self, claim_id: str, path_name: str | None = None) -> tuple[list[str], Path]:
        """Build unique branch and worktree arguments for a later independent writer."""
        isolated_path = Path(self.temporary_directory.name) / (path_name or f"worktree-{claim_id}")
        return (
            ["--branch", f"codex/{claim_id}", "--worktree-path", str(isolated_path)],
            isolated_path,
        )

    def output(self, completed: subprocess.CompletedProcess[str]) -> dict[str, object]:
        """Decode one structured command result."""
        return json.loads(completed.stdout)

    def common_directory(self) -> Path:
        """Return the temporary repository's Git common directory."""
        raw = Path(self.git("rev-parse", "--git-common-dir").stdout.strip())
        return raw if raw.is_absolute() else self.repository / raw

    def registry_path(self) -> Path:
        """Return the repository-global live registry path."""
        return self.common_directory() / "agent-claims.json"

    def hot_directory(self) -> Path:
        """Return the repository-global hot journal directory."""
        return self.common_directory() / "agent-claim-events" / "hot"

    def journal_events(self) -> list[dict[str, object]]:
        """Read all hot events for lifecycle and concurrency assertions."""
        events: list[dict[str, object]] = []
        for path in sorted(self.hot_directory().glob("*.jsonl")):
            events.extend(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
        return events

    def write_daily_events(self, day: str, events: list[dict[str, object]]) -> Path:
        """Write a deterministic historical hot file for archive and report tests."""
        self.hot_directory().mkdir(parents=True, exist_ok=True)
        path = self.hot_directory() / f"{day}.jsonl"
        path.write_text("".join(json.dumps(event, sort_keys=True) + "\n" for event in events), encoding="utf-8")
        return path

    def synthetic_event(
        self,
        event_id: str,
        timestamp: str,
        action: str,
        outcome: str,
        claim_id: str,
        **values: object,
    ) -> dict[str, object]:
        """Build the minimum versioned event fixture accepted by reporting and archival."""
        event: dict[str, object] = {
            "schema_version": 1,
            "event_id": event_id,
            "timestamp": timestamp,
            "action": action,
            "outcome": outcome,
            "claim_id": claim_id,
            "journal_warnings": [],
        }
        event.update(values)
        return event

    def test_first_writer_claims_clean_primary_worktree(self) -> None:
        completed = self.claim(*self.acquire_arguments("first"), "--file", "README.md")

        self.assertEqual(0, completed.returncode, completed.stderr)
        result = self.output(completed)
        self.assertEqual("PRIMARY", result["outcome"])
        self.assertEqual(str(self.repository.resolve()), result["claim"]["worktree"])
        self.assertEqual("primary", result["target"]["mode"])

    def test_second_independent_writer_gets_isolated_worktree(self) -> None:
        first = self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        isolated, isolated_path = self.isolated_arguments("second")
        second = self.claim(
            *self.acquire_arguments("second"),
            "--file",
            "src/one.py",
            *isolated,
        )

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("ISOLATE", self.output(second)["outcome"])
        self.assertTrue((isolated_path / ".git").is_file())

    def test_simultaneous_writers_cannot_both_claim_primary(self) -> None:
        commands = [self.claim_command(*self.acquire_arguments(claim_id)) for claim_id in ("first", "second")]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for command in commands
        ]
        completed = [process.communicate() + (process.returncode,) for process in processes]
        outcomes = {json.loads(stdout)["outcome"] for stdout, _stderr, _code in completed}
        return_codes = sorted(code for _stdout, _stderr, code in completed)

        self.assertEqual([0, 4], return_codes)
        self.assertEqual({"PRIMARY", "ISOLATE_REQUIRED"}, outcomes)

    def test_exact_files_do_not_use_ancestry_overlap(self) -> None:
        first = self.claim(*self.acquire_arguments("first"), "--file", "future")
        isolated, _isolated_path = self.isolated_arguments("second")
        second = self.claim(
            *self.acquire_arguments("second"),
            "--file",
            "future/child.py",
            *isolated,
        )

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("ISOLATE", self.output(second)["outcome"])

    def test_tree_and_all_files_scopes_overlap_descendants(self) -> None:
        tree = self.claim(
            *self.acquire_arguments("tree"),
            "--tree",
            "src",
            "--scope-reason",
            "bounded source generation",
        )
        isolated, blocked_path = self.isolated_arguments("blocked")
        nested = self.claim(
            *self.acquire_arguments("blocked"),
            "--file",
            "src/one.py",
            *isolated,
        )

        self.assertEqual(0, tree.returncode, tree.stderr)
        self.assertEqual(3, nested.returncode)
        nested_result = self.output(nested)
        self.assertEqual("WAIT", nested_result["outcome"])
        self.assertEqual("tree", nested_result["overlaps"][0]["claimed_kind"])
        self.assertFalse(blocked_path.exists())

        self.claim("release", "--claim-id", "tree", "--no-change")
        all_files = self.claim(
            *self.acquire_arguments("all"),
            "--all-files",
            "--scope-reason",
            "repository migration",
        )
        blocked = self.claim(*self.acquire_arguments("other"), "--resource", "port:3000")
        exact = self.claim(*self.acquire_arguments("exact"), "--file", "docs/guide.md")
        self.assertEqual(0, all_files.returncode, all_files.stderr)
        self.assertEqual(4, blocked.returncode)
        self.assertEqual(3, exact.returncode)

    def test_broad_scope_guardrails_and_future_file_behavior(self) -> None:
        invalid_commands = (
            (["--file", "."], "use --all-files"),
            (["--file", "**"], "use --tree"),
            (["--file", "src"], "use --tree"),
            (["--tree", "README.md", "--scope-reason", "wrong kind"], "use --file"),
            (["--tree", ".", "--scope-reason", "too broad"], "use --all-files"),
            (["--tree", "src"], "add --scope-reason"),
        )
        for index, (scope_arguments, replacement) in enumerate(invalid_commands):
            with self.subTest(scope_arguments=scope_arguments):
                completed = self.claim(*self.acquire_arguments(f"invalid-{index}"), *scope_arguments)
                self.assertEqual(1, completed.returncode)
                result = self.output(completed)
                self.assertEqual("INVALID_SCOPE", result["outcome"])
                self.assertIn(replacement, result["replacement"])

        future = self.claim(*self.acquire_arguments("future"), "--file", "not-created-yet.py")
        self.assertEqual(0, future.returncode, future.stderr)

    def test_compatibility_mode_converts_directory_file_scope_with_warning(self) -> None:
        completed = self.claim(
            *self.acquire_arguments("legacy"),
            "--file",
            "src",
            "--compat-file-directories",
            "--scope-reason",
            "temporary legacy caller",
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        result = self.output(completed)
        self.assertEqual(["src"], result["claim"]["trees"])
        self.assertEqual("legacy_file_directory_scope", result["warnings"][0]["code"])

    def test_extend_adds_multiple_scopes_and_is_idempotent(self) -> None:
        acquired = self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        extended = self.claim(
            "extend",
            "--claim-id",
            "first",
            "--file",
            "future.py",
            "--resource",
            "generated:codegen",
        )
        repeated = self.claim(
            "extend",
            "--claim-id",
            "first",
            "--file",
            "future.py",
            "--resource",
            "generated:codegen",
        )

        self.assertEqual(0, acquired.returncode, acquired.stderr)
        self.assertEqual(0, extended.returncode, extended.stderr)
        added = self.output(extended)["added_scope"]
        self.assertEqual(["future.py"], added["files"])
        self.assertEqual(["generated:codegen"], added["resources"])
        repeated_result = self.output(repeated)
        self.assertEqual("EXTENDED", repeated_result["outcome"])
        self.assertEqual([], repeated_result["added_scope"]["files"])
        self.assertEqual(["future.py"], repeated_result["already_owned_scope"]["files"])

    def test_conflicting_extension_leaves_registry_byte_for_byte_unchanged(self) -> None:
        self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        isolated, _isolated_path = self.isolated_arguments("second")
        self.claim(*self.acquire_arguments("second"), "--file", "src/one.py", *isolated)
        before = self.registry_path().read_bytes()

        blocked = self.claim("extend", "--claim-id", "second", "--file", "README.md")

        self.assertEqual(3, blocked.returncode)
        self.assertEqual("WAIT", self.output(blocked)["outcome"])
        self.assertEqual(before, self.registry_path().read_bytes())

    def test_simultaneous_extensions_cannot_both_acquire_same_file(self) -> None:
        self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        isolated, _isolated_path = self.isolated_arguments("second")
        self.claim(*self.acquire_arguments("second"), "--file", "src/one.py", *isolated)
        commands = [
            self.claim_command("extend", "--claim-id", claim_id, "--file", "shared-new.py")
            for claim_id in ("first", "second")
        ]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for command in commands
        ]
        completed = [process.communicate() + (process.returncode,) for process in processes]

        self.assertEqual([0, 3], sorted(code for _stdout, _stderr, code in completed))
        self.assertEqual(
            {"EXTENDED", "WAIT"},
            {json.loads(stdout)["outcome"] for stdout, _stderr, _code in completed},
        )

    def test_extending_isolated_claim_preserves_worktree_metadata(self) -> None:
        self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        isolated, _isolated_path = self.isolated_arguments("second")
        acquired = self.claim(*self.acquire_arguments("second"), "--file", "src/one.py", *isolated)
        before = self.output(acquired)["claim"]

        extended = self.claim("extend", "--claim-id", "second", "--file", "future.py")
        after = self.output(extended)["claim"]

        for field in ("worktree", "branch", "baseline_commit", "claimed_at", "mode"):
            self.assertEqual(before[field], after[field])

    def test_linked_worktrees_share_one_journal(self) -> None:
        self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        isolated, isolated_path = self.isolated_arguments("second")
        self.claim(*self.acquire_arguments("second"), "--file", "src/one.py", *isolated)
        third_arguments, _third_path = self.isolated_arguments("third")
        third = self.claim(
            *self.acquire_arguments("third"),
            "--file",
            "docs/guide.md",
            *third_arguments,
            repo=isolated_path,
        )
        heartbeat = self.claim("heartbeat", "--claim-id", "second", repo=isolated_path)

        self.assertEqual(0, third.returncode, third.stderr)
        self.assertEqual(0, heartbeat.returncode, heartbeat.stderr)
        events = self.journal_events()
        self.assertEqual(["first", "second", "third", "second"], [event["claim_id"] for event in events])
        self.assertEqual(1, len(list(self.hot_directory().glob("*.jsonl"))))
        linked_event = next(event for event in events if event["claim_id"] == "third")
        self.assertEqual("codex/third", linked_event["worktree_id"])
        self.assertNotIn(str(self.temporary_directory.name), json.dumps(linked_event))

    def test_concurrent_journal_events_are_complete_and_unique(self) -> None:
        self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        commands = [self.claim_command("heartbeat", "--claim-id", "first") for _index in range(12)]
        processes = [
            subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for command in commands
        ]
        completed = [process.communicate() + (process.returncode,) for process in processes]

        self.assertTrue(all(code == 0 for _stdout, _stderr, code in completed))
        events = self.journal_events()
        self.assertEqual(13, len(events))
        self.assertEqual(13, len({event["event_id"] for event in events}))

    def test_journal_failure_warns_without_weakening_registry_safety(self) -> None:
        completed = self.claim(
            *self.acquire_arguments("first"),
            "--file",
            "README.md",
            environment={"AGENT_CLAIM_TEST_FAIL_JOURNAL_WRITE": "1"},
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        result = self.output(completed)
        self.assertEqual("journal_write_failed", result["warnings"][0]["code"])
        self.assertFalse(result["journal"]["persisted"])
        registry = json.loads(self.registry_path().read_text(encoding="utf-8"))
        self.assertEqual(["first"], [claim["claim_id"] for claim in registry["claims"]])
        report = self.claim("report", "--since", "2d")
        self.assertEqual(
            [{"detail": "live claim has no acquisition event", "source": "first"}],
            json.loads(report.stdout)["coverage_gaps"],
        )

    def test_released_claim_reconstructs_as_journal_lifecycle(self) -> None:
        self.claim(*self.acquire_arguments("first"), "--file", "README.md")
        self.claim("heartbeat", "--claim-id", "first")
        (self.repository / "README.md").write_text("committed\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "change")
        released = self.claim("release", "--claim-id", "first")

        self.assertEqual(0, released.returncode, released.stderr)
        events = self.journal_events()
        self.assertEqual(["PRIMARY", "HEARTBEAT", "RELEASED"], [event["outcome"] for event in events])
        self.assertEqual(self.git("rev-parse", "HEAD").stdout.strip(), events[-1]["resulting_commit"])

    def test_release_requires_clean_commit_or_explicit_no_change(self) -> None:
        acquired = self.claim(*self.acquire_arguments("first"))
        rejected = self.claim("release", "--claim-id", "first")
        (self.repository / "README.md").write_text("committed\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-m", "change")
        released = self.claim("release", "--claim-id", "first")

        self.assertEqual(0, acquired.returncode, acquired.stderr)
        self.assertEqual(1, rejected.returncode)
        self.assertEqual("RELEASE_REJECTED", self.output(rejected)["outcome"])
        self.assertEqual(0, released.returncode, released.stderr)
        self.assertEqual("RELEASED", self.output(released)["outcome"])

    def test_recovery_claim_preserves_dirty_baseline_until_checkpoint_commit(self) -> None:
        (self.repository / "README.md").write_text("recovery\n", encoding="utf-8")
        acquired = self.claim(*self.acquire_arguments("recovery"), "--allow-recovery")
        rejected = self.claim("release", "--claim-id", "recovery")
        self.git("add", "README.md")
        self.git("commit", "-m", "recovery checkpoint")
        released = self.claim("release", "--claim-id", "recovery")

        self.assertEqual(0, acquired.returncode, acquired.stderr)
        self.assertEqual("RECOVER", self.output(acquired)["outcome"])
        self.assertEqual(1, rejected.returncode)
        self.assertEqual(0, released.returncode, released.stderr)

    def test_isolated_worktrees_commit_without_global_commit_resource(self) -> None:
        self.claim(*self.acquire_arguments("first"), "--file", "first.txt")
        isolated, isolated_path = self.isolated_arguments("second")
        self.claim(*self.acquire_arguments("second"), "--file", "second.txt", *isolated)
        (self.repository / "first.txt").write_text("first\n", encoding="utf-8")
        (isolated_path / "second.txt").write_text("second\n", encoding="utf-8")
        self.git("add", "first.txt")
        self.git("add", "second.txt", worktree=isolated_path)
        processes = [
            subprocess.Popen(
                ["git", "-C", str(worktree), "commit", "-m", message],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for worktree, message in ((self.repository, "first"), (isolated_path, "second"))
        ]
        completed = [process.communicate() + (process.returncode,) for process in processes]

        self.assertTrue(all(code == 0 for _stdout, _stderr, code in completed), completed)

    def test_integration_resources_conflict_per_target_branch(self) -> None:
        main = self.claim(
            *self.acquire_arguments("main"),
            "--resource",
            "merge:integration:main",
        )
        same_target = self.claim(
            *self.acquire_arguments("same"),
            "--resource",
            "merge:integration:main",
        )
        isolated, _isolated_path = self.isolated_arguments("release")
        other_target = self.claim(
            *self.acquire_arguments("release"),
            "--resource",
            "merge:integration:release",
            *isolated,
        )

        self.assertEqual(0, main.returncode, main.stderr)
        self.assertEqual(3, same_target.returncode)
        self.assertEqual(0, other_target.returncode, other_target.stderr)

    def test_maintenance_keeps_two_hot_days_and_archives_older_days_losslessly(self) -> None:
        for day in ("2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13"):
            event = self.synthetic_event(
                f"event-{day}",
                f"{day}T12:00:00Z",
                "acquire",
                "PRIMARY",
                f"claim-{day}",
            )
            self.write_daily_events(day, [event])
        environment = {"AGENT_CLAIM_TEST_NOW": "2026-07-13T15:00:00Z"}

        maintained = self.claim("maintain-journal", "--hot-days", "2", environment=environment)
        rerun = self.claim("maintain-journal", "--hot-days", "2", environment=environment)

        self.assertEqual(0, maintained.returncode, maintained.stderr)
        self.assertEqual(0, rerun.returncode, rerun.stderr)
        self.assertEqual(
            ["2026-07-12.jsonl", "2026-07-13.jsonl"],
            sorted(path.name for path in self.hot_directory().glob("*.jsonl")),
        )
        archive_root = self.common_directory() / "agent-claim-events" / "archive" / "2026" / "07"
        summary_root = self.common_directory() / "agent-claim-events" / "journal" / "2026" / "07"
        for day in ("2026-07-10", "2026-07-11"):
            archive = archive_root / f"{day}.jsonl.gz"
            summary = summary_root / f"{day}.json"
            events = [json.loads(line) for line in gzip.decompress(archive.read_bytes()).decode().splitlines()]
            self.assertEqual([f"event-{day}"], [event["event_id"] for event in events])
            self.assertEqual(1, json.loads(summary.read_text(encoding="utf-8"))["raw_event_count"])
        self.assertEqual([], self.output(rerun)["archived"])

    def test_archive_interruption_leaves_hot_file_for_safe_rerun(self) -> None:
        event = self.synthetic_event("old", "2026-07-10T12:00:00Z", "acquire", "PRIMARY", "old")
        hot = self.write_daily_events("2026-07-10", [event])
        environment = {
            "AGENT_CLAIM_TEST_NOW": "2026-07-13T15:00:00Z",
            "AGENT_CLAIM_TEST_FAIL_ARCHIVE_BEFORE_VALIDATE": "1",
        }

        interrupted = self.claim("maintain-journal", environment=environment)

        self.assertEqual(1, interrupted.returncode)
        self.assertTrue(hot.exists())
        archive = self.common_directory() / "agent-claim-events" / "archive" / "2026" / "07" / "2026-07-10.jsonl.gz"
        self.assertFalse(archive.exists())
        completed = self.claim(
            "maintain-journal",
            environment={"AGENT_CLAIM_TEST_NOW": "2026-07-13T15:00:00Z"},
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse(hot.exists())

    def test_archive_validation_failure_preserves_hot_source(self) -> None:
        event = self.synthetic_event("old", "2026-07-10T12:00:00Z", "acquire", "PRIMARY", "old")
        hot = self.write_daily_events("2026-07-10", [event])
        archive = self.common_directory() / "agent-claim-events" / "archive" / "2026" / "07" / "2026-07-10.jsonl.gz"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(gzip.compress(b'{"different":"event"}\n'))

        completed = self.claim(
            "maintain-journal",
            environment={"AGENT_CLAIM_TEST_NOW": "2026-07-13T15:00:00Z"},
        )

        self.assertEqual(1, completed.returncode)
        self.assertEqual("JOURNAL_MAINTENANCE_FAILED", self.output(completed)["outcome"])
        self.assertTrue(hot.exists())

    def test_report_groups_waits_and_distinguishes_contention_kinds(self) -> None:
        events = [
            self.synthetic_event(
                "wait-1",
                "2026-07-12T10:00:00Z",
                "acquire",
                "WAIT",
                "blocked",
                overlaps=[
                    {
                        "scope_kind": "path",
                        "requested_kind": "file",
                        "requested": "src/one.py",
                        "claimed_kind": "file",
                        "claimed": "src/one.py",
                    },
                    {
                        "scope_kind": "resource",
                        "requested_kind": "resource",
                        "requested": "port:3000",
                        "claimed_kind": "resource",
                        "claimed": "port:3000",
                    },
                ],
                journal_warnings=[{"code": "prior_journal_warning"}],
            ),
            self.synthetic_event(
                "wait-2",
                "2026-07-12T10:02:00Z",
                "acquire",
                "WAIT",
                "blocked",
                overlaps=[
                    {
                        "scope_kind": "path",
                        "requested_kind": "file",
                        "requested": "src/one.py",
                        "claimed_kind": "tree",
                        "claimed": "src",
                    }
                ],
            ),
            self.synthetic_event(
                "acquire",
                "2026-07-12T10:05:00Z",
                "acquire",
                "PRIMARY",
                "blocked",
                requested_scopes={
                    "files": [],
                    "trees": ["src"],
                    "all_files": False,
                    "resources": ["merge:integration:main"],
                    "scope_reason": "source migration",
                },
            ),
            self.synthetic_event("release", "2026-07-12T10:06:00Z", "release", "RELEASED", "blocked"),
            self.synthetic_event("isolate", "2026-07-12T10:10:00Z", "acquire", "ISOLATE", "isolated"),
            self.synthetic_event("isolate-release", "2026-07-12T10:11:00Z", "release", "RELEASED", "isolated"),
            self.synthetic_event("recover", "2026-07-12T10:20:00Z", "acquire", "RECOVER", "recovery"),
            self.synthetic_event("recover-release", "2026-07-12T10:21:00Z", "release", "RELEASED", "recovery"),
        ]
        self.write_daily_events("2026-07-12", events)
        environment = {"AGENT_CLAIM_TEST_NOW": "2026-07-13T10:00:00Z"}
        registry_before = self.registry_path().read_bytes() if self.registry_path().exists() else None
        journal_before = (self.hot_directory() / "2026-07-12.jsonl").read_bytes()

        completed = self.claim("report", "--since", "2d", environment=environment)

        self.assertEqual(0, completed.returncode, completed.stderr)
        report = json.loads(completed.stdout)
        metrics = report["metrics"]
        self.assertEqual(
            {"primary": 1, "isolated": 1, "recovery": 1},
            metrics["successful_acquisitions"],
        )
        self.assertEqual(2, metrics["wait_attempt_count"])
        self.assertEqual(1, len(metrics["wait_episodes"]))
        self.assertEqual(300.0, metrics["wait_episodes"][0]["duration_seconds"])
        self.assertEqual("src/one.py", metrics["top_contention"]["exact_files"][0]["scope"])
        self.assertEqual("src/one.py", metrics["top_contention"]["trees"][0]["scope"])
        self.assertEqual("port:3000", metrics["top_contention"]["resources"][0]["scope"])
        self.assertEqual(60.0, metrics["claim_duration_seconds"]["median"])
        self.assertEqual("source migration", metrics["broad_scopes"]["reasons"][0]["scope"])
        self.assertEqual("merge:integration:main", metrics["integration_resources"][0]["scope"])
        self.assertEqual(1, metrics["journal_warning_count"])
        self.assertEqual(registry_before, self.registry_path().read_bytes() if self.registry_path().exists() else None)
        self.assertEqual(journal_before, (self.hot_directory() / "2026-07-12.jsonl").read_bytes())

    def test_daily_boundaries_use_utc_not_local_daylight_saving(self) -> None:
        event = self.synthetic_event("old", "2026-11-01T23:30:00Z", "acquire", "PRIMARY", "old")
        old = self.write_daily_events("2026-11-01", [event])
        current = self.write_daily_events(
            "2026-11-03",
            [self.synthetic_event("current", "2026-11-03T00:01:00Z", "heartbeat", "HEARTBEAT", "current")],
        )

        completed = self.claim(
            "maintain-journal",
            "--hot-days",
            "2",
            environment={"AGENT_CLAIM_TEST_NOW": "2026-11-03T00:05:00Z", "TZ": "America/Toronto"},
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertFalse(old.exists())
        self.assertTrue(current.exists())


if __name__ == "__main__":
    unittest.main()
