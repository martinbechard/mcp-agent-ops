# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Creates durable hierarchy-plan sources and applies exact item mutations before regenerating HTML.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from mcp_agent_ops.hierarchy.renderer import (
    _is_branch,
    _is_sequence,
    _load_hierarchy,
    _theme_css,
    _value_text,
    render_hierarchy_html,
)

_PLAN_SCHEMA = "mcp-agent-ops-hierarchy-plan"
_PLAN_VERSION = 1
_NUMBER_PATH = re.compile(r"[1-9][0-9]*(?:\.[1-9][0-9]*)*")


@dataclass
class _PlanItem:
    text: str
    complete: bool = False
    children: list[_PlanItem] = field(default_factory=list)

    def payload(self) -> dict[str, object]:
        return {
            "text": self.text,
            "complete": self.complete,
            "children": [child.payload() for child in self.children],
        }

    @classmethod
    def from_payload(cls, payload: object) -> _PlanItem:
        if not isinstance(payload, dict):
            raise ValueError("Hierarchy plan items must be JSON objects.")
        text = payload.get("text")
        complete = payload.get("complete")
        children = payload.get("children")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Hierarchy plan item text must be a non-empty string.")
        if not isinstance(complete, bool):
            raise ValueError("Hierarchy plan item completion must be true or false.")
        if not isinstance(children, list):
            raise ValueError("Hierarchy plan item children must be a JSON array.")
        return cls(text=text, complete=complete, children=[cls.from_payload(child) for child in children])


@dataclass
class _PlanDocument:
    path: Path
    title: str
    theme: str
    themes_folder: str | None
    html_filename: str
    root_label: str
    items: list[_PlanItem]

    def payload(self) -> dict[str, object]:
        return {
            "schema": _PLAN_SCHEMA,
            "version": _PLAN_VERSION,
            "title": self.title,
            "theme": self.theme,
            "themesFolder": self.themes_folder,
            "htmlFilename": self.html_filename,
            "rootLabel": self.root_label,
            "items": [item.payload() for item in self.items],
        }


@dataclass(frozen=True)
class _ItemLocation:
    siblings: list[_PlanItem]
    index: int
    path: tuple[int, ...]

    @property
    def item(self) -> _PlanItem:
        return self.siblings[self.index]


class HierarchyPlanItemReference(BaseModel):
    """Identify one plan item by its current dotted number and displayed label."""

    identifier: str
    label: str


class HierarchyPlanNextTask(HierarchyPlanItemReference):
    """Describe the next incomplete executable leaf and its outermost-first context."""

    parents: list[HierarchyPlanItemReference] = Field(default_factory=list)


class HierarchyPlanUpdateResult(BaseModel):
    """Report a successful durable mutation and the next executable plan task.

    `automatically_completed` lists newly completed ancestors from the closest parent
    outward. `next_task` is the first incomplete leaf in depth-first plan order, or
    `None` after every executable leaf is complete.
    """

    success: bool
    plan_path: Path
    automatically_completed: list[HierarchyPlanItemReference] = Field(default_factory=list)
    next_task: HierarchyPlanNextTask | None = None


def _item_text(value: object) -> str:
    text = _value_text(value).strip()
    if not text:
        raise ValueError("Hierarchy plan item text must not be empty.")
    return text


def _items_from_hierarchy(value: object) -> list[_PlanItem]:
    items: list[_PlanItem] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            label = _item_text(key)
            if _is_branch(child):
                items.append(_PlanItem(text=label, children=_items_from_hierarchy(child)))
            else:
                items.append(_PlanItem(text=f"{label}: {_item_text(child)}"))
        return items
    if _is_sequence(value):
        for child in value:
            if _is_branch(child):
                items.extend(_items_from_hierarchy(child))
            else:
                items.append(_PlanItem(text=_item_text(child)))
        return items
    raise TypeError("Hierarchy plan branches must be mappings or sequences.")


def _plan_root(hierarchy: object, title: str) -> tuple[str, list[_PlanItem]]:
    if isinstance(hierarchy, Mapping) and len(hierarchy) == 1:
        root_label, root_value = next(iter(hierarchy.items()))
        if _is_branch(root_value):
            return _item_text(root_label), _items_from_hierarchy(root_value)
    return title, _items_from_hierarchy(hierarchy)


def _new_item(text: str) -> _PlanItem:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("New hierarchy plan item text must be a non-empty string.")
    return _PlanItem(text=text.strip())


def _walk_locations(
    items: list[_PlanItem], prefix: tuple[int, ...] = ()
) -> list[_ItemLocation]:
    locations: list[_ItemLocation] = []
    for index, item in enumerate(items):
        path = (*prefix, index + 1)
        locations.append(_ItemLocation(items, index, path))
        locations.extend(_walk_locations(item.children, path))
    return locations


def _locate_item(items: list[_PlanItem], target: str) -> _ItemLocation:
    if not isinstance(target, str) or not target.strip():
        raise ValueError("Hierarchy plan target must be a dotted path or exact item title.")
    normalized = target.strip()
    if _NUMBER_PATH.fullmatch(normalized) is not None:
        siblings = items
        location: _ItemLocation | None = None
        for part in normalized.split("."):
            index = int(part) - 1
            if index >= len(siblings):
                raise ValueError(f"Hierarchy target '{target}' does not identify an item.")
            path = (*(() if location is None else location.path), index + 1)
            location = _ItemLocation(siblings, index, path)
            siblings = location.item.children
        if location is None:
            raise ValueError(f"Hierarchy target '{target}' does not identify an item.")
        return location

    matches = [location for location in _walk_locations(items) if location.item.text == normalized]
    if not matches:
        raise ValueError(f"Hierarchy target '{target}' does not identify an item.")
    if len(matches) > 1:
        raise ValueError(f"Hierarchy target '{target}' matches more than one item; use its dotted path.")
    return matches[0]


def _location_at_path(items: list[_PlanItem], path: tuple[int, ...]) -> _ItemLocation:
    siblings = items
    location: _ItemLocation | None = None
    current_path: tuple[int, ...] = ()
    for part in path:
        index = part - 1
        location = _ItemLocation(siblings, index, (*current_path, part))
        current_path = location.path
        siblings = location.item.children
    if location is None:
        raise ValueError("Hierarchy item path must not be empty.")
    return location


def _identifier(path: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in path)


def _item_reference(path: tuple[int, ...], item: _PlanItem) -> HierarchyPlanItemReference:
    return HierarchyPlanItemReference(identifier=_identifier(path), label=item.text)


def _ancestor_locations(
    items: list[_PlanItem], path: tuple[int, ...]
) -> list[_ItemLocation]:
    return [
        _location_at_path(items, path[:depth])
        for depth in range(len(path) - 1, 0, -1)
    ]


def _set_subtree_completion(item: _PlanItem, complete: bool) -> None:
    item.complete = complete
    for child in item.children:
        _set_subtree_completion(child, complete)


def _recompute_branch_completion(items: list[_PlanItem]) -> None:
    for item in items:
        if item.children:
            _recompute_branch_completion(item.children)
            item.complete = all(child.complete for child in item.children)


def _next_executable_task(items: list[_PlanItem]) -> HierarchyPlanNextTask | None:
    def visit(
        siblings: list[_PlanItem],
        prefix: tuple[int, ...],
        parents: tuple[HierarchyPlanItemReference, ...],
    ) -> HierarchyPlanNextTask | None:
        for index, item in enumerate(siblings, start=1):
            path = (*prefix, index)
            if item.children:
                next_task = visit(
                    item.children,
                    path,
                    (*parents, _item_reference(path, item)),
                )
                if next_task is not None:
                    return next_task
            elif not item.complete:
                return HierarchyPlanNextTask(
                    identifier=_identifier(path),
                    label=item.text,
                    parents=list(parents),
                )
        return None

    return visit(items, (), ())


def _completed_paths(items: list[_PlanItem], prefix: tuple[int, ...] = ()) -> list[str]:
    completed: list[str] = []
    for index, item in enumerate(items, start=1):
        path = (*prefix, index)
        if item.complete:
            completed.append(".".join(str(part) for part in path))
        completed.extend(_completed_paths(item.children, path))
    return completed


def _hierarchy_items(items: list[_PlanItem]) -> list[object]:
    hierarchy: list[object] = []
    for item in items:
        if item.children:
            hierarchy.append({item.text: _hierarchy_items(item.children)})
        else:
            hierarchy.append(item.text)
    return hierarchy


def _render_plan(document: _PlanDocument) -> None:
    render_hierarchy_html(
        {document.root_label: _hierarchy_items(document.items)},
        title=document.title,
        theme=document.theme,
        themes_folder=document.themes_folder,
        numbering=True,
        checkboxes=True,
        completed_items=_completed_paths(document.items),
        output_filename=document.html_filename,
        output_folder=document.path.parent,
    )


def _write_plan(document: _PlanDocument) -> None:
    if document.path.is_symlink():
        raise ValueError("Hierarchy plan file must not be a symbolic link.")
    document.path.write_text(_plan_json(document), encoding="utf-8")


def _plan_json(document: _PlanDocument) -> str:
    """Serialize one canonical hierarchy plan for persistence or an inline MCP result."""
    return json.dumps(document.payload(), ensure_ascii=False, indent=2) + "\n"


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Hierarchy plan field '{key}' must be a non-empty string.")
    return value


def _plan_filename(output_filename: str | Path) -> Path:
    """Validate and return one hierarchy-plan HTML base filename."""
    filename = Path(output_filename)
    if not filename.name or filename.name in {".", ".."} or filename.parent != Path("."):
        raise ValueError("Hierarchy plan output_filename must be a base file name without a directory.")
    if filename.suffix.lower() != ".html":
        raise ValueError("Hierarchy plan output_filename must use a .html extension.")
    return filename


def _new_plan_document(
    source: object,
    *,
    path: Path,
    title: str,
    theme: str,
    themes_folder: str | Path | None,
    html_filename: str,
    completed_items: Sequence[str],
) -> _PlanDocument:
    """Normalize hierarchy input into one canonical plan document."""
    hierarchy = _load_hierarchy(source)
    root_label, items = _plan_root(hierarchy, title)
    for target in completed_items:
        _set_subtree_completion(_locate_item(items, target).item, True)
    _recompute_branch_completion(items)
    stored_themes_folder = (
        None if themes_folder is None else str(Path(themes_folder).expanduser().resolve())
    )
    return _PlanDocument(
        path=path,
        title=title,
        theme=theme,
        themes_folder=stored_themes_folder,
        html_filename=html_filename,
        root_label=root_label,
        items=items,
    )


def _load_plan(path: str | Path) -> _PlanDocument:
    expanded = Path(path).expanduser()
    if expanded.is_symlink():
        raise ValueError("Hierarchy plan file must not be a symbolic link.")
    if not expanded.is_file():
        raise FileNotFoundError(f"Hierarchy plan file does not exist: {expanded}")
    if expanded.suffix.lower() != ".json":
        raise ValueError("Hierarchy plan file must use a .json extension.")
    try:
        payload = json.loads(expanded.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("Hierarchy plan file is not valid JSON.") from error
    if not isinstance(payload, dict):
        raise ValueError("Hierarchy plan file must contain a JSON object.")
    if payload.get("schema") != _PLAN_SCHEMA or payload.get("version") != _PLAN_VERSION:
        raise ValueError("Hierarchy plan file has an unsupported schema or version.")
    themes_folder = payload.get("themesFolder")
    if themes_folder is not None and not isinstance(themes_folder, str):
        raise ValueError("Hierarchy plan field 'themesFolder' must be a string or null.")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("Hierarchy plan field 'items' must be a JSON array.")
    return _PlanDocument(
        path=expanded.resolve(),
        title=_required_string(payload, "title"),
        theme=_required_string(payload, "theme"),
        themes_folder=themes_folder,
        html_filename=_required_string(payload, "htmlFilename"),
        root_label=_required_string(payload, "rootLabel"),
        items=[_PlanItem.from_payload(item) for item in raw_items],
    )


def create_hierarchy_plan(
    source: object,
    *,
    title: str = "Hierarchy plan",
    theme: str = "default",
    themes_folder: str | Path | None = None,
    output_filename: str | Path,
    output_folder: str | Path | None = None,
    completed_items: Sequence[str] = (),
) -> Path:
    """Create a durable numbered plan plus its same-named HTML rendering.

    Use this function when an agent must create a hierarchy that it will mutate later.
    The function normalizes supported hierarchy input into a JSON plan document, writes
    a sibling HTML file, and returns the JSON path required by `update_hierarchy_plan`.

    Args:
        source: Any in-memory, JSON, YAML, or source-file hierarchy accepted by
            `render_hierarchy_html`.
        title: Title used in the HTML page and as the default structural root label.
        theme: Packaged or caller-owned theme base name.
        themes_folder: Optional folder containing the caller-owned `<theme>.css` file.
        output_filename: Base HTML filename. The function also writes the same base name
            with a `.json` extension and returns that JSON path.
        output_folder: Optional destination folder, created when needed. The current
            directory is used when this parameter is omitted.
        completed_items: Exact dotted paths or unique item titles to mark complete in
            the initial plan. Selecting a branch also completes its descendants.

    Returns:
        The resolved path of the durable JSON plan file.

    Raises:
        FileNotFoundError: If a selected source or theme file does not exist.
        TypeError: If the hierarchy contains unsupported values.
        ValueError: If hierarchy parsing, output naming, initial targeting, theme
            selection, or plan serialization fails.

    Side effects:
        Reads selected source and theme files, creates the destination folder, and writes
        one JSON plan file plus one same-named HTML file.
    """
    filename = _plan_filename(output_filename)
    folder = Path.cwd() if output_folder is None else Path(output_folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    plan_target = folder.resolve() / filename.with_suffix(".json").name
    if plan_target.is_symlink():
        raise ValueError("Hierarchy plan file must not be a symbolic link.")
    plan_path = plan_target.resolve()
    document = _new_plan_document(
        source,
        path=plan_path,
        title=title,
        theme=theme,
        themes_folder=themes_folder,
        html_filename=filename.name,
        completed_items=completed_items,
    )
    _render_plan(document)
    _write_plan(document)
    return plan_path


def hierarchy_plan_json(
    source: object,
    *,
    title: str = "Hierarchy plan",
    theme: str = "default",
    themes_folder: str | Path | None = None,
    output_filename: str | Path,
    completed_items: Sequence[str] = (),
) -> str:
    """Return canonical hierarchy-plan JSON without creating files.

    This adapter-facing operation applies the same hierarchy normalization and initial
    completion rules as durable plan creation. The retained HTML filename allows a caller
    to persist the returned document later using the standard plan schema.

    Args:
        source: Any in-memory, JSON, YAML, or source-file hierarchy accepted by
            `render_hierarchy_html`.
        title: Plan title and default structural root label.
        theme: Packaged or caller-owned theme base name retained in the plan.
        themes_folder: Optional authorized folder retained for a caller-owned theme.
        output_filename: Base HTML filename retained in the canonical plan document.
        completed_items: Exact dotted paths or unique titles initially marked complete.

    Returns:
        Indented canonical JSON ending with one newline.

    Raises:
        FileNotFoundError: If a selected source file does not exist.
        TypeError: If the hierarchy contains unsupported values.
        ValueError: If hierarchy parsing, output naming, or initial targeting fails.

    This function reads a selected source file but performs no filesystem mutation.
    """
    filename = _plan_filename(output_filename)
    _theme_css(theme, themes_folder)
    return _plan_json(_new_plan_document(
        source,
        path=Path(filename.with_suffix(".json").name),
        title=title,
        theme=theme,
        themes_folder=themes_folder,
        html_filename=filename.name,
        completed_items=completed_items,
    ))


def update_hierarchy_plan(
    plan_path: str | Path,
    target: str,
    *,
    completed: bool | None = None,
    text: str | None = None,
    add_child: str | None = None,
    replace_children: Sequence[str] | None = None,
    add_peer_after: str | None = None,
) -> HierarchyPlanUpdateResult:
    """Apply one exact item mutation and regenerate a durable hierarchy plan.

    The target can be a one-based dotted path such as `1.6.1` or an exact item title.
    Title targeting must resolve to one item. Dotted paths are parsed component by
    component, so a mutation for `1.6.1` cannot affect `1.6.10` or `1.6.1.1`.

    Args:
        plan_path: JSON path returned by `create_hierarchy_plan`.
        target: Exact dotted path or exact unique item title.
        completed: New completion state for the target item. A branch mutation applies
            the same state to its complete descendant subtree.
        text: Replacement text for the target item.
        add_child: Text for one child appended beneath the target item.
        replace_children: Complete ordered replacement for the target's child items.
            An empty sequence removes every child.
        add_peer_after: Text for one sibling inserted immediately after the target item.

    Returns:
        A successful mutation result containing the resolved JSON plan path, any
        ancestors completed by the mutation, and the next incomplete executable leaf
        with its parent context. The next task is null when no incomplete leaf remains.

    Raises:
        FileNotFoundError: If the plan or selected theme file does not exist.
        ValueError: If the plan is invalid, the target is missing or ambiguous, the
            mutation value is invalid, or the call supplies other than one mutation.

    Side effects:
        Reads and rewrites the JSON plan file and regenerates its same-named HTML file.
    """
    actions = (
        completed is not None,
        text is not None,
        add_child is not None,
        replace_children is not None,
        add_peer_after is not None,
    )
    if sum(actions) != 1:
        raise ValueError("update_hierarchy_plan requires exactly one mutation.")
    document = _load_plan(plan_path)
    location = _locate_item(document.items, target)
    ancestors_before = [
        (ancestor, ancestor.item.complete)
        for ancestor in _ancestor_locations(document.items, location.path)
    ]
    if completed is not None:
        if not isinstance(completed, bool):
            raise ValueError("completed must be true or false.")
        _set_subtree_completion(location.item, completed)
    elif text is not None:
        location.item.text = _new_item(text).text
    elif add_child is not None:
        location.item.children.append(_new_item(add_child))
    elif replace_children is not None:
        if isinstance(replace_children, (str, bytes, bytearray)):
            raise ValueError("replace_children must be a sequence of item text values.")
        location.item.children = [_new_item(child) for child in replace_children]
    elif add_peer_after is not None:
        location.siblings.insert(location.index + 1, _new_item(add_peer_after))
    _recompute_branch_completion(document.items)
    automatically_completed = (
        [
            _item_reference(ancestor.path, ancestor.item)
            for ancestor, was_complete in ancestors_before
            if not was_complete and ancestor.item.complete
        ]
        if completed is True
        else []
    )
    _render_plan(document)
    _write_plan(document)
    return HierarchyPlanUpdateResult(
        success=True,
        plan_path=document.path,
        automatically_completed=automatically_completed,
        next_task=_next_executable_task(document.items),
    )
