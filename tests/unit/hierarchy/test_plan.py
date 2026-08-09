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

    assert update_hierarchy_plan(plan_path, "1.1", text="First task") == plan_path
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
