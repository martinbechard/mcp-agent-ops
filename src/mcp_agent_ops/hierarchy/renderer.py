# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Renders JSON/YAML data as safe, themed, copyable HTML trees with numbering and report markers.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from html import escape
from itertools import count
from pathlib import Path
from typing import TypeGuard, overload

import yaml

_SOURCE_SUFFIXES = frozenset({".json", ".yaml", ".yml"})
_THEME_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_THEMES_ROOT = Path(__file__).resolve().with_name("themes")
_SCALAR_TYPES = (str, int, float, bool, date, type(None))

_SCRIPT = """(() => {
  const root = document.querySelector("[data-hierarchy-root]");
  if (!root) return;
  const levelControls = document.querySelectorAll("[data-level]");
  const copyControl = document.querySelector('[data-action="copy"]');
  const copyStatus = document.querySelector("[data-copy-status]");
  let copyResetTimer;

  const setExpanded = (button, expanded) => {
    button.setAttribute("aria-expanded", String(expanded));
    const children = document.getElementById(button.getAttribute("aria-controls"));
    if (children) children.hidden = !expanded;
  };

  const setVisibleLevel = (level) => {
    const visibleLevel = level === "all" ? Number.POSITIVE_INFINITY : Number(level);
    root.querySelectorAll(".tree-toggle").forEach((button) => {
      const depth = Number(button.getAttribute("data-depth"));
      setExpanded(button, depth < visibleLevel);
    });
    levelControls.forEach((control) => {
      control.setAttribute("aria-pressed", String(control.getAttribute("data-level") === level));
    });
  };

  root.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const button = event.target.closest(".tree-toggle");
    if (!button || !root.contains(button)) return;
    setExpanded(button, button.getAttribute("aria-expanded") !== "true");
    levelControls.forEach((control) => control.setAttribute("aria-pressed", "false"));
  });

  document.querySelectorAll('[data-action="expand"], [data-action="collapse"]').forEach((control) => {
    control.addEventListener("click", () => {
      const level = control.getAttribute("data-action") === "expand" ? "all" : "1";
      setVisibleLevel(level);
    });
  });

  levelControls.forEach((control) => {
    control.addEventListener("click", () => {
      setVisibleLevel(control.getAttribute("data-level"));
    });
  });

  const payloadText = () => {
    const lines = [];
    const appendList = (list, depth) => {
      Array.from(list.children).forEach((node) => {
        if (!(node instanceof Element) || !node.classList.contains("tree-node")) return;
        const line = node.querySelector(":scope > .node-line .tree-line-content");
        if (line) {
          const marker = node.querySelector(":scope > .node-line > .tree-checkbox");
          const completion = marker
            ? marker.classList.contains("is-checked") ? "[x] " : "[ ] "
            : "";
          const text = line.textContent.replace(/\\s+/g, " ").trim();
          lines.push(`${"  ".repeat(depth)}${completion}${text}`);
        }
        const children = node.querySelector(":scope > .tree-children");
        if (children) appendList(children, depth + 1);
      });
    };
    appendList(root, 0);
    return lines.join("\\n");
  };

  const fallbackCopy = (payload) => {
    const activeElement = document.activeElement;
    const field = document.createElement("textarea");
    field.value = payload;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const copied = document.execCommand("copy");
    field.remove();
    if (activeElement instanceof HTMLElement) activeElement.focus();
    return copied;
  };

  const writePayload = async (payload) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(payload);
        return true;
      } catch {
        return fallbackCopy(payload);
      }
    }
    return fallbackCopy(payload);
  };

  if (copyControl) {
    copyControl.addEventListener("click", async () => {
      const copied = await writePayload(payloadText());
      copyControl.textContent = copied ? "Copied" : "Copy failed";
      if (copyStatus) {
        copyStatus.textContent = copied
          ? "Hierarchy content copied."
          : "Could not copy the hierarchy content. Select and copy it manually.";
      }
      window.clearTimeout(copyResetTimer);
      copyResetTimer = window.setTimeout(() => {
        copyControl.textContent = "Copy content";
        if (copyStatus) copyStatus.textContent = "";
      }, 2000);
    });
  }
})();"""


def _is_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_branch(value: object) -> bool:
    return isinstance(value, Mapping) or _is_sequence(value)


def _validate_hierarchy(value: object, ancestors: set[int], *, root: bool = False) -> None:
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("Hierarchy contains a cycle and cannot be rendered.")
        ancestors.add(identity)
        try:
            for key, child in value.items():
                if not isinstance(key, _SCALAR_TYPES):
                    raise TypeError("Hierarchy mapping keys must be scalar values.")
                _validate_hierarchy(child, ancestors)
        finally:
            ancestors.remove(identity)
        return
    if _is_sequence(value):
        identity = id(value)
        if identity in ancestors:
            raise ValueError("Hierarchy contains a cycle and cannot be rendered.")
        ancestors.add(identity)
        try:
            for child in value:
                _validate_hierarchy(child, ancestors)
        finally:
            ancestors.remove(identity)
        return
    if root:
        raise TypeError("Hierarchy root must be a mapping or sequence.")
    if not isinstance(value, _SCALAR_TYPES):
        raise TypeError(
            "Hierarchy values must be JSON/YAML scalars, mappings, or sequences; "
            f"got {type(value).__name__}."
        )


def _parse_content(content: str, suffix: str | None = None) -> object:
    try:
        if suffix == ".json":
            return json.loads(content)
        if suffix in {".yaml", ".yml"}:
            return yaml.safe_load(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return yaml.safe_load(content)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise ValueError("Hierarchy content is not valid JSON or YAML.") from error


def _read_source_file(path: Path) -> object:
    expanded = path.expanduser()
    if not expanded.is_file():
        raise FileNotFoundError(f"Hierarchy source file does not exist: {expanded}")
    suffix = expanded.suffix.lower()
    if suffix not in _SOURCE_SUFFIXES:
        raise ValueError("Hierarchy source file must use a .json, .yaml, or .yml extension.")
    return _parse_content(expanded.read_text(encoding="utf-8"), suffix)


def _string_source_path(value: str) -> Path | None:
    stripped = value.strip()
    if not stripped or "\n" in value or "\r" in value or stripped.startswith(("{", "[")):
        return None
    candidate = Path(value).expanduser()
    try:
        if candidate.exists():
            return candidate
    except OSError:
        return None
    return None


def _load_hierarchy(source: object) -> object:
    if isinstance(source, Path):
        hierarchy = _read_source_file(source)
    elif isinstance(source, str):
        source_path = _string_source_path(source)
        hierarchy = _read_source_file(source_path) if source_path is not None else _parse_content(source)
    else:
        hierarchy = source
    _validate_hierarchy(hierarchy, set(), root=True)
    return hierarchy


def _value_kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _value_text(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _branch_entries(value: object, *, numbering: bool = False) -> list[tuple[str | None, object]]:
    if isinstance(value, Mapping):
        return [(str(key), child) for key, child in value.items()]
    if _is_sequence(value):
        if numbering:
            return [(None, child) for child in value]
        return [(f"[{index}]", child) for index, child in enumerate(value)]
    raise TypeError("Branch values must be mappings or sequences.")


def _number_text(number_path: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in number_path)


def _completion_marker_html(
    label: str | None,
    number_path: tuple[int, ...],
    *,
    numbering: bool,
) -> str:
    marker = _number_text(number_path) if numbering else label
    safe_marker = escape(marker or "item", quote=True)
    return (
        '<span class="tree-checkbox" role="img" '
        f'aria-label="{safe_marker} incomplete"></span>'
    )


def _render_node(
    label: str | None,
    value: object,
    identifiers: count[int],
    number_path: tuple[int, ...],
    *,
    numbering: bool,
    checkboxes: bool,
) -> str:
    safe_label = escape(label, quote=True) if label is not None else None
    completion_marker = (
        _completion_marker_html(label, number_path, numbering=numbering)
        if checkboxes and number_path
        else ""
    )
    number = (
        f'<span class="tree-number">{_number_text(number_path)}</span>' if numbering and number_path else ""
    )
    key = f'<span class="tree-key">{safe_label}</span>' if safe_label is not None else ""
    number_key_space = " " if number and key else ""
    if not _is_branch(value):
        kind = _value_kind(value)
        safe_value = escape(_value_text(value), quote=True)
        separator = '<span class="tree-separator" aria-hidden="true">:</span>' if key else ""
        label_value_space = " " if number or key else ""
        return (
            '<li class="tree-node tree-leaf" role="treeitem">'
            '<div class="node-line">'
            f'{completion_marker}<span class="tree-line-content">'
            f"{number}{number_key_space}{key}{separator}{label_value_space}"
            f'<span class="tree-value type-{kind}">{safe_value}</span></span>'
            "</div></li>"
        )

    entries = _branch_entries(value, numbering=numbering)
    node_id = f"hierarchy-node-{next(identifiers)}"
    children = "".join(
        _render_node(
            child_label,
            child,
            identifiers,
            (*number_path, child_index),
            numbering=numbering,
            checkboxes=checkboxes,
        )
        for child_index, (child_label, child) in enumerate(entries, start=1)
    )
    return (
        '<li class="tree-node tree-branch" role="treeitem">'
        '<div class="node-line">'
        f"{completion_marker}"
        f'<button type="button" class="tree-toggle" data-depth="{len(number_path)}" '
        f'aria-expanded="true" aria-controls="{node_id}">'
        '<span class="tree-chevron" aria-hidden="true"></span>'
        f'<span class="tree-line-content">{number}{number_key_space}{key}</span>'
        "</button></div>"
        f'<ul class="tree-children" id="{node_id}" role="group">{children}</ul>'
        "</li>"
    )


def _read_css(path: Path, description: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"{description} file does not exist: {path}")
    content = path.read_text(encoding="utf-8")
    if re.search(r"</style", content, flags=re.IGNORECASE):
        raise ValueError(f"{description} CSS must not contain a closing style tag.")
    return content


def _theme_css(theme: str, themes_folder: str | Path | None) -> str:
    if _THEME_NAME.fullmatch(theme) is None:
        raise ValueError("Theme must be a simple base name containing only letters, numbers, hyphens, or underscores.")
    base_css = _read_css(_THEMES_ROOT / "base.css", "Base theme")
    themes_root = _THEMES_ROOT if themes_folder is None else Path(themes_folder).expanduser().resolve()
    candidate = (themes_root / f"{theme}.css").resolve()
    if candidate.parent != themes_root:
        raise ValueError("Theme file resolves outside the themes folder.")
    return f"{base_css}\n{_read_css(candidate, 'Theme')}"


def _render_document(
    hierarchy: object,
    title: str,
    theme: str,
    css: str,
    *,
    numbering: bool,
    checkboxes: bool,
) -> str:
    entries = _branch_entries(hierarchy, numbering=numbering)
    identifiers: count[int] = count(1)
    transparent_singleton = (
        numbering and isinstance(hierarchy, Mapping) and len(entries) == 1 and _is_branch(entries[0][1])
    )
    if transparent_singleton:
        label, value = entries[0]
        nodes = _render_node(
            label,
            value,
            identifiers,
            (),
            numbering=True,
            checkboxes=checkboxes,
        )
    else:
        nodes = "".join(
            _render_node(
                label,
                value,
                identifiers,
                (index,),
                numbering=numbering,
                checkboxes=checkboxes,
            )
            for index, (label, value) in enumerate(entries, start=1)
        )
    safe_title = escape(title, quote=True)
    safe_theme = escape(theme, quote=True)
    return f"""<!doctype html>
<html lang="en" data-theme="{safe_theme}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{safe_title}</title>
  <style>
{css}
  </style>
</head>
<body>
  <main class="hierarchy-document">
    <header class="document-header">
      <div>
        <h1>{safe_title}</h1>
      </div>
      <div class="tree-controls">
        <div class="tree-actions" aria-label="Tree controls">
          <button type="button" data-action="copy">Copy content</button>
          <button type="button" data-action="expand">Expand all</button>
          <button type="button" data-action="collapse">Collapse all</button>
        </div>
        <div class="tree-levels" aria-label="Expand tree to level">
          <span class="tree-level-label">Levels</span>
          <button type="button" data-level="1" aria-pressed="false" aria-label="Expand through level 1">1</button>
          <button type="button" data-level="2" aria-pressed="false" aria-label="Expand through level 2">2</button>
          <button type="button" data-level="3" aria-pressed="false" aria-label="Expand through level 3">3</button>
          <button type="button" data-level="all" aria-pressed="true" aria-label="Expand all levels">All</button>
        </div>
        <span class="copy-status" role="status" aria-live="polite" data-copy-status></span>
      </div>
    </header>
    <ul class="hierarchy-tree" role="tree" data-hierarchy-root>{nodes}</ul>
  </main>
  <script>
{_SCRIPT}
  </script>
</body>
</html>
"""


def _save_html(html: str, output_filename: str | Path, output_folder: str | Path | None) -> Path:
    filename = Path(output_filename)
    if not filename.name or filename.name in {".", ".."} or filename.parent != Path("."):
        raise ValueError("output_filename must be a base file name without a directory.")
    folder = Path.cwd() if output_folder is None else Path(output_folder).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    resolved_folder = folder.resolve()
    target = resolved_folder / filename.name
    if target.is_symlink():
        raise ValueError("Output file must not be a symbolic link.")
    target.write_text(html, encoding="utf-8")
    return target.resolve()


@overload
def render_hierarchy_html(
    source: object,
    *,
    title: str = "Hierarchy",
    theme: str = "default",
    themes_folder: str | Path | None = None,
    numbering: bool = False,
    checkboxes: bool = False,
    output_filename: None = None,
    output_folder: str | Path | None = None,
) -> str: ...


@overload
def render_hierarchy_html(
    source: object,
    *,
    title: str = "Hierarchy",
    theme: str = "default",
    themes_folder: str | Path | None = None,
    numbering: bool = False,
    checkboxes: bool = False,
    output_filename: str | Path,
    output_folder: str | Path | None = None,
) -> Path: ...


def render_hierarchy_html(
    source: object,
    *,
    title: str = "Hierarchy",
    theme: str = "default",
    themes_folder: str | Path | None = None,
    numbering: bool = False,
    checkboxes: bool = False,
    output_filename: str | Path | None = None,
    output_folder: str | Path | None = None,
) -> str | Path:
    """Render hierarchical data as a safe, self-contained, collapsible HTML document.

    Use this function for agent plans, reports, outlines, and other mapping-or-sequence
    structures that benefit from nested expand and collapse controls. Mapping order and
    sequence order are preserved. Every document includes controls for showing only
    levels 1, 2, or 3, or expanding the complete tree. A copy control writes the complete
    hierarchy as indented plain text, including descendants hidden by collapsed branches.

    Args:
        source: An in-memory mapping or non-string sequence, JSON or YAML text, an
            existing `.json`, `.yaml`, or `.yml` filename, or a `Path` to such a file.
            String filenames are recognized when they exist; use `Path` for an explicit
            filename that may not exist.
        title: Document title shown in the browser title bar and page header.
        theme: Base name of the selected CSS file, without the `.css` extension.
        themes_folder: Optional folder containing `<theme>.css`. When omitted, the
            packaged themes are used. Packaged base layout CSS is always included.
        numbering: Whether to prefix nodes with one-based dotted hierarchy numbers such
            as `1.2.3`. A singleton root mapping whose value is another branch remains
            visible as an unnumbered structural label; its children begin at `1`.
            Synthetic sequence labels such as `[0]` are hidden when numbering is enabled.
        checkboxes: Whether to place a static incomplete marker before each trackable
            node's number or label. An unnumbered singleton root wrapper is structural
            and receives no marker. The marker is read-only and does not change or write
            back to the source data.
        output_filename: Optional base filename. When supplied, the HTML is written and
            the resolved output `Path` is returned; otherwise the complete HTML is returned.
        output_folder: Optional destination folder, created when needed. It is valid only
            when `output_filename` is supplied and defaults to the current directory.

    Returns:
        The complete HTML string when `output_filename` is absent, or the resolved path
        of the saved self-contained HTML file when it is present.

    Raises:
        FileNotFoundError: If a source or selected theme file does not exist.
        TypeError: If the root is not a mapping or sequence, or a nested value is not a
            JSON/YAML scalar, mapping, or sequence.
        ValueError: If parsing fails, the hierarchy is cyclic, a theme or output name is
            unsafe, or `output_folder` is supplied without `output_filename`.

    Side effects:
        Reads source or theme files when selected. Creates the output folder and writes
        one UTF-8 HTML file when `output_filename` is supplied.
    """
    if output_filename is None and output_folder is not None:
        raise ValueError("output_folder requires output_filename.")
    hierarchy = _load_hierarchy(source)
    css = _theme_css(theme, themes_folder)
    html = _render_document(
        hierarchy,
        title,
        theme,
        css,
        numbering=numbering,
        checkboxes=checkboxes,
    )
    if output_filename is None:
        return html
    return _save_html(html, output_filename, output_folder)
