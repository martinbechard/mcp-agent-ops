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
        "agent-workflow.html": ("Agent Workflow", "blueprint", "bounded execution scope"),
        "document-outline.html": (
            "Document Outline",
            "midnight",
            "Define the capabilities that the document covers.",
        ),
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
    assert index.count("<iframe") == 4
    assert 'src="delivery-plan.html"' in index
    assert 'src="incident-review.html"' in index
    assert 'src="agent-workflow.html"' in index
    assert 'src="document-outline.html"' in index
    assert index.count('sandbox="allow-scripts"') == 4
    assert index.count('class="style-callout"') == 4
    assert index.count("<p>Presentation parameters</p>") == 4
    for theme in ("default", "midnight", "outline", "blueprint"):
        assert f"theme=&quot;{theme}&quot;" in index
    assert 'themes_folder=&quot;examples/hierarchy-gallery/themes&quot;' in index
    assert index.count("numbering=True") == 2
    assert index.count("numbering=False") == 2
    assert index.count("checkboxes=True") == 1
    assert index.count("checkboxes=False") == 3

    agent_workflow = (tmp_path / "agent-workflow.html").read_text(encoding="utf-8")
    assert "background-size: 24px 24px" in agent_workflow
    assert 'data-theme="blueprint"' in agent_workflow

    delivery_plan = (tmp_path / "delivery-plan.html").read_text(encoding="utf-8")
    assert '<span class="tree-number">5.1</span>' in delivery_plan
    assert 'aria-label="Mark 5.1 complete"' in delivery_plan
    assert '<span class="tree-number">1</span><span class="tree-key">Objective</span>' in delivery_plan
    assert 'class="tree-toggle" data-depth="0"' in delivery_plan
    assert 'aria-label="Mark item complete"' not in delivery_plan
    assert 'class="tree-checkbox"' in delivery_plan
    assert 'data-level="1"' in delivery_plan
    assert 'data-level="2"' in delivery_plan
    assert 'data-level="3"' in delivery_plan
    assert 'data-level="all"' in delivery_plan
    assert "[0]" not in delivery_plan
    for identifier_label in (
        "delivery_plan",
        "target_date",
        "in_progress",
        "design_approval",
        "analytics_delay",
    ):
        assert identifier_label not in delivery_plan
    for document_label in ("Delivery plan", "Target date", "In progress", "Design approval", "Analytics delay"):
        assert document_label in delivery_plan

    document_outline = (tmp_path / "document-outline.html").read_text(encoding="utf-8")
    assert '<span class="tree-number">2.1</span>' in document_outline
    assert "Product Requirements Document" in document_outline
    assert 'class="tree-checkbox"' not in document_outline
    assert "[0]" not in document_outline
