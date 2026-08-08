# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies safe self-contained HTML trees, numbering, tracking controls, inputs, and themes.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from pathlib import Path

import pytest

from mcp_agent_ops.hierarchy import render_hierarchy_html


def test_renders_nested_mappings_and_sequences_as_an_interactive_tree() -> None:
    rendered = render_hierarchy_html(
        {
            "Plan": {
                "steps": [
                    {"task": "Discover", "complete": True},
                    {"task": "Implement", "owner": None},
                ]
            }
        },
        title="Delivery plan",
    )

    assert isinstance(rendered, str)
    assert rendered.startswith("<!doctype html>")
    assert "<title>Delivery plan</title>" in rendered
    assert 'class="tree-toggle"' in rendered
    assert 'aria-expanded="true"' in rendered
    assert '<span class="tree-key">[0]</span>' in rendered
    assert '<span class="tree-value type-string">Discover</span>' in rendered
    assert '<span class="tree-value type-boolean">true</span>' in rendered
    assert '<span class="tree-value type-null">null</span>' in rendered
    assert "Expand all" in rendered
    assert "Collapse all" in rendered
    assert 'root.addEventListener("click"' in rendered


def test_renders_progressive_level_controls_and_branch_depth_metadata() -> None:
    rendered = render_hierarchy_html({"Plan": {"phases": [{"tasks": ["Write"]}]}})

    assert 'class="tree-levels" aria-label="Expand tree to level"' in rendered
    for level in (1, 2, 3):
        assert f'data-level="{level}" aria-pressed="false"' in rendered
        assert f'aria-label="Expand through level {level}"' in rendered
        assert f'data-depth="{level}"' in rendered
    assert 'data-level="all" aria-pressed="true"' in rendered
    assert 'aria-label="Expand all levels"' in rendered
    assert "depth < visibleLevel" in rendered


def test_optionally_renders_dotted_hierarchical_numbers_and_tracking_checkboxes() -> None:
    rendered = render_hierarchy_html(
        {"Plan": {"phases": [{"tasks": ["Write", "Review"]}]}},
        numbering=True,
        checkboxes=True,
    )

    for number in ("1", "1.1", "1.1.1", "1.1.1.1", "1.1.1.1.1", "1.1.1.1.2"):
        assert f'<span class="tree-number">{number}</span>' in rendered
        assert f'aria-label="Mark {number} complete"' in rendered
    assert rendered.count('class="tree-checkbox"') == 6
    assert "[0]" not in rendered
    assert rendered.index('class="tree-checkbox"') < rendered.index('<span class="tree-number">1</span>')


def test_escapes_titles_keys_and_values_before_inserting_them_into_html() -> None:
    rendered = render_hierarchy_html(
        {"<script>alert('key')</script>": "</script><img src=x onerror=alert('value')>"},
        title="<b>Unsafe</b>",
    )

    assert "<b>Unsafe</b>" not in rendered
    assert "&lt;b&gt;Unsafe&lt;/b&gt;" in rendered
    assert "<script>alert('key')</script>" not in rendered
    assert "&lt;script&gt;alert(&#x27;key&#x27;)&lt;/script&gt;" in rendered
    assert "<img src=x" not in rendered
    assert "&lt;/script&gt;&lt;img src=x onerror=alert(&#x27;value&#x27;)&gt;" in rendered


def test_accepts_json_or_yaml_content_and_existing_file_names(tmp_path: Path) -> None:
    from_json = render_hierarchy_html('{"plan": [{"task": "Discover"}]}')
    from_yaml = render_hierarchy_html("plan:\n  - task: Verify\n    due: 2026-08-10\n")
    source_file = tmp_path / "plan.yaml"
    source_file.write_text("plan:\n  - task: Publish\n", encoding="utf-8")
    from_path = render_hierarchy_html(source_file)
    from_string_path = render_hierarchy_html(str(source_file))

    assert "Discover" in from_json
    assert "Verify" in from_yaml
    assert "2026-08-10" in from_yaml
    assert "Publish" in from_path
    assert from_string_path == from_path


def test_saves_self_contained_html_and_returns_the_resolved_output_path(tmp_path: Path) -> None:
    output = render_hierarchy_html(
        {"plan": ["Write", "Review"]},
        output_filename="plan.html",
        output_folder=tmp_path / "reports" / "nested",
    )

    assert isinstance(output, Path)
    assert output == (tmp_path / "reports" / "nested" / "plan.html").resolve()
    assert output.is_file()
    saved = output.read_text(encoding="utf-8")
    assert saved.startswith("<!doctype html>")
    assert "Write" in saved
    assert "<style>" in saved
    assert "<script>" in saved


def test_loads_builtin_and_caller_supplied_theme_files(tmp_path: Path) -> None:
    outlined = render_hierarchy_html({"plan": ["Review"]}, theme="outline")
    midnight = render_hierarchy_html({"plan": ["Review"]}, theme="midnight")
    themes = tmp_path / "themes"
    themes.mkdir()
    (themes / "solarized.css").write_text(":root { --accent: #b58900; }\n", encoding="utf-8")
    custom = render_hierarchy_html(
        {"plan": ["Review"]},
        theme="solarized",
        themes_folder=themes,
    )

    assert 'data-theme="outline"' in outlined
    assert "--accent: #8250df" in outlined
    assert 'data-theme="midnight"' in midnight
    assert "--background: #080d18" in midnight
    assert 'data-theme="solarized"' in custom
    assert "--accent: #b58900" in custom


def test_rejects_invalid_sources_themes_and_output_combinations(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="root must be a mapping or sequence"):
        render_hierarchy_html("plain scalar")
    with pytest.raises(FileNotFoundError, match="Hierarchy source file does not exist"):
        render_hierarchy_html(tmp_path / "missing.json")
    with pytest.raises(ValueError, match="simple base name"):
        render_hierarchy_html({"plan": []}, theme="../secret")
    with pytest.raises(FileNotFoundError, match="Theme file does not exist"):
        render_hierarchy_html({"plan": []}, theme="missing")
    with pytest.raises(ValueError, match="requires output_filename"):
        render_hierarchy_html({"plan": []}, output_folder=tmp_path)
    with pytest.raises(ValueError, match="base file name"):
        render_hierarchy_html(
            {"plan": []},
            output_filename="nested/plan.html",
            output_folder=tmp_path,
        )
    with pytest.raises(ValueError, match="base file name"):
        render_hierarchy_html({"plan": []}, output_filename="..", output_folder=tmp_path)


def test_rejects_recursive_in_memory_structures() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(ValueError, match="cycle"):
        render_hierarchy_html(cyclic)
