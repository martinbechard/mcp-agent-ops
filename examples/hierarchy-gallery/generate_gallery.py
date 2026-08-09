# Copyright (c) 2026 Martin.Bechard@DevConsult.ca
# AI attribution: Generated with AI assistance.
# Summary: Builds a hierarchy gallery with theme variants, example states, and presentation callouts.
# Design: docs/design/high-level/architecture.md
# Test plan: docs/reference/test-plan.md

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from mcp_agent_ops.hierarchy import create_hierarchy_plan, render_hierarchy_html

_GALLERY_ROOT = Path(__file__).resolve().parent
_REPOSITORY_ROOT = _GALLERY_ROOT.parents[1]
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$")


@dataclass(frozen=True)
class _Demo:
    slug: str
    title: str
    description: str
    source: object
    theme: str
    themes_folder: Path | None = None
    numbering: bool = False
    checkboxes: bool = False
    initially_complete: tuple[str, ...] = ()


@dataclass
class _OutlineNode:
    title: str
    level: int
    body: list[str] = field(default_factory=list)
    children: list[_OutlineNode] = field(default_factory=list)


def _outline_value(node: _OutlineNode) -> object:
    if node.children:
        if node.body:
            raise ValueError(f"Markdown outline branch '{node.title}' must not contain body text.")
        result: dict[str, object] = {}
        for child in node.children:
            if child.title in result:
                raise ValueError(f"Markdown outline contains duplicate sibling heading '{child.title}'.")
            result[child.title] = _outline_value(child)
        return result
    body = " ".join(node.body).strip()
    if not body:
        raise ValueError(f"Markdown outline leaf '{node.title}' must contain review text.")
    return body


def _load_markdown_outline(path: Path) -> dict[str, object]:
    roots: list[_OutlineNode] = []
    stack: list[_OutlineNode] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        heading = _MARKDOWN_HEADING.fullmatch(line)
        if heading is None:
            if not stack:
                raise ValueError(f"Markdown outline body appears before its first heading at line {line_number}.")
            stack[-1].body.append(line)
            continue

        level = len(heading.group(1))
        if not stack and level != 1:
            raise ValueError("Markdown outline must begin with one level-one heading.")
        if stack and level > stack[-1].level + 1:
            raise ValueError(f"Markdown outline skips a heading level at line {line_number}.")
        while stack and stack[-1].level >= level:
            stack.pop()

        node = _OutlineNode(title=heading.group(2), level=level)
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)

    if len(roots) != 1:
        raise ValueError("Markdown outline must contain exactly one level-one heading.")
    root = roots[0]
    return {root.title: _outline_value(root)}


def _demos() -> list[_Demo]:
    agent_workflow = {
        "agent_workflow": {
            "intake": {
                "inputs": ["accepted work item", "repository guidance", "runtime constraints"],
                "outcome": "bounded execution scope",
            },
            "execution": {
                "phases": [
                    {"name": "discover", "evidence": ["callers", "contracts", "tests"]},
                    {"name": "implement", "evidence": ["focused test", "minimal change"]},
                    {"name": "verify", "evidence": ["full tests", "static checks"]},
                ],
                "parallel_work_allowed": True,
            },
            "handoff": {
                "include": ["outcome", "verification", "commit"],
                "claim_unverified_work": False,
            },
        }
    }
    return [
        _Demo(
            slug="delivery-plan",
            title="Delivery Plan",
            description=(
                "Numbered YAML input with two completed tracking items and the packaged default theme."
            ),
            source=_GALLERY_ROOT / "data" / "delivery-plan.yaml",
            theme="default",
            numbering=True,
            checkboxes=True,
            initially_complete=("1", "2"),
        ),
        _Demo(
            slug="document-outline",
            title="Document Outline",
            description=(
                "Reviewable Markdown headings rendered with numbering, no checkboxes, "
                "and the paper-like packaged outline theme."
            ),
            source=_load_markdown_outline(_GALLERY_ROOT / "data" / "document-outline.md"),
            theme="outline",
            numbering=True,
        ),
        _Demo(
            slug="incident-review",
            title="Incident Review",
            description="Full JSON content with the packaged midnight theme.",
            source=(_GALLERY_ROOT / "data" / "incident-review.json").read_text(encoding="utf-8"),
            theme="midnight",
        ),
        _Demo(
            slug="agent-workflow",
            title="Agent Workflow",
            description="In-memory Python data with a caller-supplied blueprint theme.",
            source=agent_workflow,
            theme="blueprint",
            themes_folder=_GALLERY_ROOT / "themes",
        ),
    ]


def _presentation_parameters(demo: _Demo) -> str:
    parameters = [f'theme="{demo.theme}"']
    if demo.themes_folder is not None:
        try:
            theme_folder = demo.themes_folder.relative_to(_REPOSITORY_ROOT).as_posix()
        except ValueError:
            theme_folder = demo.themes_folder.as_posix()
        parameters.append(f'themes_folder="{theme_folder}"')
    parameters.extend((f"numbering={demo.numbering}", f"checkboxes={demo.checkboxes}"))
    return "\n".join(parameters)


def _gallery_index(demos: list[_Demo]) -> str:
    cards = "\n".join(
        f"""      <article class="gallery-card">
        <div class="card-copy">
          <p class="eyebrow">{escape(demo.theme)} theme</p>
          <h2>{escape(demo.title)}</h2>
          <p>{escape(demo.description)}</p>
          <aside class="style-callout" aria-label="Presentation parameters">
            <p>Presentation parameters</p>
            <pre><code>{escape(_presentation_parameters(demo))}</code></pre>
          </aside>
          <a href="{escape(demo.slug, quote=True)}.html">Open full page</a>
        </div>
        <iframe
          src="{escape(demo.slug, quote=True)}.html"
          title="{escape(demo.title, quote=True)} interactive preview"
          loading="lazy"
          sandbox="allow-scripts"
        ></iframe>
      </article>"""
        for demo in demos
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hierarchical HTML Gallery</title>
  <style>
    :root {{ color-scheme: light; font-family: "Avenir Next", "Segoe UI", ui-sans-serif, system-ui, sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; color: #172033; background: #eef2f7; }}
    main {{ width: min(1440px, calc(100% - 2rem)); margin: 2.5rem auto; }}
    header {{ max-width: 760px; margin-bottom: 2rem; }}
    h1 {{ margin: 0; font-size: clamp(2rem, 5vw, 3.75rem); letter-spacing: -0.045em; }}
    header p {{ color: #526174; font-size: 1.05rem; line-height: 1.65; }}
    .gallery {{ display: grid; gap: 1.5rem; }}
    .gallery-card {{ overflow: hidden; border: 1px solid #ced7e3; border-radius: 18px; background: white;
      box-shadow: 0 20px 55px rgb(22 34 51 / 9%); }}
    .card-copy {{ padding: 1.25rem 1.5rem; border-bottom: 1px solid #dbe2ea; }}
    .card-copy h2 {{ margin: 0.2rem 0 0.35rem; }}
    .card-copy p {{ margin: 0; color: #5c6a7d; }}
    .card-copy a {{ display: inline-block; margin-top: 0.8rem; color: #255ab5; font-weight: 700; }}
    .eyebrow {{ color: #7c3aed !important; font-family: ui-monospace, "SFMono-Regular", Consolas, monospace;
      font-size: 0.72rem; font-weight: 800; letter-spacing: 0.09em; text-transform: uppercase; }}
    .style-callout {{ margin-top: 1rem; padding: 0.8rem 0.9rem; border-left: 3px solid #7c3aed;
      border-radius: 0 10px 10px 0; background: #f5f3ff; }}
    .style-callout p {{ margin: 0 0 0.35rem; color: #6d28d9; font-size: 0.7rem; font-weight: 800;
      letter-spacing: 0.08em; text-transform: uppercase; }}
    .style-callout pre {{ margin: 0; overflow-x: auto; color: #312e81;
      font: 0.78rem/1.55 ui-monospace, "SFMono-Regular", Consolas, monospace; white-space: pre-wrap; }}
    iframe {{ display: block; width: 100%; height: 620px; border: 0; background: #f8fafc; }}
    @media (min-width: 1100px) {{
      .gallery {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .gallery-card:last-child:nth-child(odd) {{ grid-column: 1 / -1; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <p class="eyebrow">Renderer examples</p>
      <h1>Hierarchical HTML Gallery</h1>
      <p>{len(demos)} interactive examples show structured inputs, a Markdown document outline,
        three packaged themes, and one caller-supplied theme.</p>
    </header>
    <section class="gallery" aria-label="Interactive hierarchy examples">
{cards}
    </section>
  </main>
</body>
</html>
"""


def _build_gallery(output_folder: Path) -> Path:
    output_folder.mkdir(parents=True, exist_ok=True)
    demos = _demos()
    for demo in demos:
        if demo.checkboxes:
            create_hierarchy_plan(
                demo.source,
                title=demo.title,
                theme=demo.theme,
                themes_folder=demo.themes_folder,
                output_filename=f"{demo.slug}.html",
                output_folder=output_folder,
                completed_items=demo.initially_complete,
            )
        else:
            render_hierarchy_html(
                demo.source,
                title=demo.title,
                theme=demo.theme,
                themes_folder=demo.themes_folder,
                numbering=demo.numbering,
                checkboxes=demo.checkboxes,
                output_filename=f"{demo.slug}.html",
                output_folder=output_folder,
            )
    index_path = output_folder / "index.html"
    index_path.write_text(_gallery_index(demos), encoding="utf-8")
    return index_path.resolve()


def main() -> int:
    """Generate the complete renderer gallery and report its index path.

    Returns:
        Zero after all example pages and the gallery index are written successfully.

    Raises:
        OSError: If source files cannot be read or generated files cannot be written.
        TypeError: If a checked-in example is not a supported hierarchy.
        ValueError: If a checked-in example or theme violates the renderer contract.

    Side effects:
        Parses command-line arguments, creates the selected output folder, writes the index
        and four example HTML files, and prints the resolved gallery index path.
    """
    parser = argparse.ArgumentParser(description="Build the hierarchical HTML renderer gallery.")
    parser.add_argument(
        "--output-folder",
        type=Path,
        default=_GALLERY_ROOT / "build",
        help="Destination folder for the generated index and self-contained examples.",
    )
    arguments = parser.parse_args()
    index_path = _build_gallery(arguments.output_folder)
    print(f"Gallery generated: {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
