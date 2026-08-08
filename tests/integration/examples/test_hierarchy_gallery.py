# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Verifies the checked-in hierarchy examples generate a complete browsable gallery.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

import subprocess
import sys
from pathlib import Path


def test_gallery_generator_builds_index_and_interactive_examples(tmp_path: Path) -> None:
    repository = Path(__file__).parents[3]
    generator = repository / "examples" / "hierarchy-gallery" / "generate_gallery.py"

    completed = subprocess.run(
        [sys.executable, str(generator), "--output-folder", str(tmp_path)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    assert str((tmp_path / "index.html").resolve()) in completed.stdout
    pages = {
        "delivery-plan.html": ("Delivery Plan", "default", "Release the customer portal refresh"),
        "incident-review.html": ("Incident Review", "outline", "A retry policy amplified"),
        "agent-workflow.html": ("Agent Workflow", "midnight", "bounded execution scope"),
    }
    for filename, (title, theme, example_value) in pages.items():
        content = (tmp_path / filename).read_text(encoding="utf-8")
        assert content.startswith("<!doctype html>")
        assert f"<title>{title}</title>" in content
        assert f'data-theme="{theme}"' in content
        assert example_value in content
        assert 'class="tree-toggle"' in content
        assert "Expand all" in content

    index = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert index.count("<iframe") == 3
    assert 'src="delivery-plan.html"' in index
    assert 'src="incident-review.html"' in index
    assert 'src="agent-workflow.html"' in index
    assert index.count('sandbox="allow-scripts"') == 3

    delivery_plan = (tmp_path / "delivery-plan.html").read_text(encoding="utf-8")
    assert '<span class="tree-number">1.5.1</span>' in delivery_plan
    assert 'aria-label="Mark 1.5.1 complete"' in delivery_plan
    assert 'class="tree-checkbox"' in delivery_plan
    assert "[0]" not in delivery_plan
