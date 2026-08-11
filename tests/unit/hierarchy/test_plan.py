# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies durable hierarchy-plan creation, exact item targeting, mutations, and HTML regeneration.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import json
from pathlib import Path

import pytest

from mcp_agent_ops.hierarchy import create_hierarchy_plan, update_hierarchy_plan


def _read_plan(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_create_returns_the_durable_json_path_and_renders_its_html_peer(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {
            "Delivery plan": {
                "Prepare": {"Tasks": ["Draft the change", "Review the change"]},
                "Release": "Publish the approved change",
            }
        },
        title="Delivery plan",
        output_filename="delivery-plan.html",
        output_folder=tmp_path,
        completed_items=("1.1.1",),
    )

    assert plan_path == (tmp_path / "delivery-plan.json").resolve()
    assert plan_path.is_file()
    assert _read_plan(plan_path)["htmlFilename"] == "delivery-plan.html"
    html = (tmp_path / "delivery-plan.html").read_text(encoding="utf-8")
    assert '<span class="tree-number">1.1.1</span>' in html
    assert 'aria-label="1.1.1 complete"' in html
    assert "Draft the change" in html


def test_updates_completion_and_text_by_exact_path_or_unique_title(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {"Plan": {"Tasks": [f"Task {index}" for index in range(1, 11)]}},
        output_filename="plan.html",
        output_folder=tmp_path,
    )

    renamed = update_hierarchy_plan(plan_path, "1.1", text="First task")
    assert renamed.success is True
    assert renamed.plan_path == plan_path
    update_hierarchy_plan(plan_path, "First task", completed=True)
    assert 'aria-label="1.1 complete"' in (tmp_path / "plan.html").read_text(encoding="utf-8")
    update_hierarchy_plan(plan_path, "First task", completed=False)

    plan = _read_plan(plan_path)
    tasks = plan["items"]
    assert isinstance(tasks, list)
    task_group = tasks[0]
    assert isinstance(task_group, dict)
    children = task_group["children"]
    assert isinstance(children, list)
    assert children[0] == {"text": "First task", "complete": False, "children": []}
    assert children[9] == {"text": "Task 10", "complete": False, "children": []}
    html = (tmp_path / "plan.html").read_text(encoding="utf-8")
    assert "First task" in html
    assert "Task 10" in html
    assert 'aria-label="1.1 incomplete"' in html


def test_completion_returns_next_leaf_and_completes_finished_parent(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {
            "Plan": {
                "First group": ["First task", "Second task"],
                "Second group": ["First of second", "Second of second"],
            }
        },
        output_filename="plan.html",
        output_folder=tmp_path,
    )

    first = update_hierarchy_plan(plan_path, "1.1", completed=True)

    assert first.success is True
    assert first.plan_path == plan_path
    assert first.automatically_completed == []
    assert first.next_task is not None
    assert first.next_task.model_dump(mode="json") == {
        "identifier": "1.2",
        "label": "Second task",
        "parents": [{"identifier": "1", "label": "First group"}],
    }

    second = update_hierarchy_plan(plan_path, "1.2", completed=True)

    assert [item.model_dump() for item in second.automatically_completed] == [
        {"identifier": "1", "label": "First group"}
    ]
    assert second.next_task is not None
    assert second.next_task.model_dump(mode="json") == {
        "identifier": "2.1",
        "label": "First of second",
        "parents": [{"identifier": "2", "label": "Second group"}],
    }
    plan = _read_plan(plan_path)
    first_group = plan["items"][0]
    assert isinstance(first_group, dict)
    assert first_group["complete"] is True


def test_completion_cascades_through_every_finished_ancestor(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {
            "Plan": {
                "First phase": {"Only group": ["First task", "Last task"]},
                "Second phase": "Release",
            }
        },
        output_filename="plan.html",
        output_folder=tmp_path,
        completed_items=("1.1.1",),
    )

    result = update_hierarchy_plan(plan_path, "1.1.2", completed=True)

    assert [item.model_dump() for item in result.automatically_completed] == [
        {"identifier": "1.1", "label": "Only group"},
        {"identifier": "1", "label": "First phase"},
    ]
    assert result.next_task is not None
    assert result.next_task.model_dump(mode="json") == {
        "identifier": "2",
        "label": "Second phase: Release",
        "parents": [],
    }


def test_next_task_uses_plan_order_and_complete_parent_context(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {
            "Plan": {
                "First phase": {"Only group": ["First task", "Second task"]},
                "Later task": "Release",
            }
        },
        output_filename="plan.html",
        output_folder=tmp_path,
    )

    result = update_hierarchy_plan(plan_path, "2", completed=True)

    assert result.next_task is not None
    assert result.next_task.model_dump(mode="json") == {
        "identifier": "1.1.1",
        "label": "First task",
        "parents": [
            {"identifier": "1", "label": "First phase"},
            {"identifier": "1.1", "label": "Only group"},
        ],
    }


def test_reopening_child_clears_completed_ancestors(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {"Plan": {"Group": ["First task", "Second task"]}},
        output_filename="plan.html",
        output_folder=tmp_path,
    )
    update_hierarchy_plan(plan_path, "1.1", completed=True)
    update_hierarchy_plan(plan_path, "1.2", completed=True)

    result = update_hierarchy_plan(plan_path, "1.1", completed=False)

    assert result.automatically_completed == []
    assert result.next_task is not None
    assert result.next_task.identifier == "1.1"
    plan = _read_plan(plan_path)
    group = plan["items"][0]
    assert isinstance(group, dict)
    assert group["complete"] is False


def test_branch_completion_applies_to_descendants_before_selecting_next_task(
    tmp_path: Path,
) -> None:
    plan_path = create_hierarchy_plan(
        {
            "Plan": {
                "Outer": {"Group": ["First task", "Second task"]},
                "Release": "Publish",
            }
        },
        output_filename="plan.html",
        output_folder=tmp_path,
    )

    result = update_hierarchy_plan(plan_path, "1.1", completed=True)

    assert [item.model_dump() for item in result.automatically_completed] == [
        {"identifier": "1", "label": "Outer"}
    ]
    assert result.next_task is not None
    assert result.next_task.identifier == "2"
    plan = _read_plan(plan_path)
    outer = plan["items"][0]
    assert isinstance(outer, dict)
    group = outer["children"][0]
    assert isinstance(group, dict)
    assert group["complete"] is True
    assert all(child["complete"] is True for child in group["children"])


def test_structural_mutations_reopen_completed_ancestors(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {"Plan": {"Group": ["First task"]}},
        output_filename="plan.html",
        output_folder=tmp_path,
        completed_items=("1",),
    )

    child_result = update_hierarchy_plan(plan_path, "1", add_child="Second task")

    assert child_result.next_task is not None
    assert child_result.next_task.identifier == "1.2"
    plan = _read_plan(plan_path)
    group = plan["items"][0]
    assert isinstance(group, dict)
    assert group["complete"] is False

    update_hierarchy_plan(plan_path, "1.2", completed=True)
    peer_result = update_hierarchy_plan(plan_path, "1.2", add_peer_after="Third task")

    assert peer_result.next_task is not None
    assert peer_result.next_task.identifier == "1.3"
    plan = _read_plan(plan_path)
    group = plan["items"][0]
    assert isinstance(group, dict)
    assert group["complete"] is False

    update_hierarchy_plan(plan_path, "1.3", completed=True)
    replaced = update_hierarchy_plan(plan_path, "1", replace_children=("Replacement",))

    assert replaced.next_task is not None
    assert replaced.next_task.identifier == "1.1"
    plan = _read_plan(plan_path)
    group = plan["items"][0]
    assert isinstance(group, dict)
    assert group["complete"] is False


def test_reopening_branch_reopens_its_complete_subtree(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {"Plan": {"Outer": {"Group": ["First task", "Second task"]}}},
        output_filename="plan.html",
        output_folder=tmp_path,
    )
    update_hierarchy_plan(plan_path, "1", completed=True)

    result = update_hierarchy_plan(plan_path, "1.1", completed=False)

    assert result.next_task is not None
    assert result.next_task.identifier == "1.1.1"
    plan = _read_plan(plan_path)
    outer = plan["items"][0]
    assert isinstance(outer, dict)
    group = outer["children"][0]
    assert isinstance(group, dict)
    assert outer["complete"] is False
    assert group["complete"] is False
    assert all(child["complete"] is False for child in group["children"])


def test_adds_and_replaces_children_and_inserts_a_peer_after_the_target(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {"Plan": ["Research", "Release"]},
        output_filename="plan.html",
        output_folder=tmp_path,
    )

    update_hierarchy_plan(plan_path, "1", add_child="Interview users")
    update_hierarchy_plan(plan_path, "Research", add_peer_after="Design")
    update_hierarchy_plan(plan_path, "Research", replace_children=("Map journey", "Approve scope"))
    update_hierarchy_plan(plan_path, "2", text="Detailed design")

    plan = _read_plan(plan_path)
    assert plan["items"] == [
        {
            "text": "Research",
            "complete": False,
            "children": [
                {"text": "Map journey", "complete": False, "children": []},
                {"text": "Approve scope", "complete": False, "children": []},
            ],
        },
        {"text": "Detailed design", "complete": False, "children": []},
        {"text": "Release", "complete": False, "children": []},
    ]
    html = (tmp_path / "plan.html").read_text(encoding="utf-8")
    for number, text in (
        ("1", "Research"),
        ("1.1", "Map journey"),
        ("1.2", "Approve scope"),
        ("2", "Detailed design"),
        ("3", "Release"),
    ):
        assert f'<span class="tree-number">{number}</span>' in html
        assert text in html
    assert "Interview users" not in html


def test_rejects_ambiguous_missing_or_multi_action_mutations(tmp_path: Path) -> None:
    plan_path = create_hierarchy_plan(
        {"Plan": ["Duplicate", "Duplicate"]},
        output_filename="plan.html",
        output_folder=tmp_path,
    )

    with pytest.raises(ValueError, match="matches more than one"):
        update_hierarchy_plan(plan_path, "Duplicate", text="Renamed")
    with pytest.raises(ValueError, match="does not identify an item"):
        update_hierarchy_plan(plan_path, "1.6.1", text="Renamed")
    with pytest.raises(ValueError, match="exactly one mutation"):
        update_hierarchy_plan(plan_path, "1", text="Renamed", completed=True)
    with pytest.raises(ValueError, match="exactly one mutation"):
        update_hierarchy_plan(plan_path, "1")


def test_rejects_invalid_durable_plan_output_names(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="base file name"):
        create_hierarchy_plan(
            {"Plan": ["Task"]},
            output_filename="nested/plan.html",
            output_folder=tmp_path,
        )
    with pytest.raises(ValueError, match="html extension"):
        create_hierarchy_plan(
            {"Plan": ["Task"]},
            output_filename="plan.json",
            output_folder=tmp_path,
        )
