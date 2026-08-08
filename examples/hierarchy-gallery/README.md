# Hierarchical HTML Gallery

This gallery demonstrates four source and presentation combinations:

- `delivery-plan.yaml` uses document-style labels and a transparent singleton wrapper. Its plan
  entries use dotted numbering, tracking checkboxes, and the packaged `default` theme.
- [`document-outline.md`](data/document-outline.md) provides a reviewable heading outline. Its
  headings and leaf text form the in-memory hierarchy that the renderer displays with dotted
  numbering, no checkboxes, and the packaged `midnight` theme.
- `incident-review.json` is read as full JSON content and rendered with the packaged `outline` theme.
- an in-memory Python mapping is rendered with the packaged `midnight` theme.

Markdown parsing belongs only to this example generator. The public renderer accepts structured
Python data, JSON/YAML content, and JSON/YAML files; it does not accept Markdown directly.

For the complete API and behavior contract, see the
[hierarchical HTML renderer reference](../../docs/reference/hierarchy-html-renderer.md).

Generate all examples and the gallery index from the repository root:

```bash
uv run python examples/hierarchy-gallery/generate_gallery.py
```

Then open `examples/hierarchy-gallery/build/index.html` in a browser. Each card contains a live,
collapsible preview, progressive `1`, `2`, `3`, and `All` level controls, and a link to the
complete self-contained page.

To write somewhere else, pass an explicit destination:

```bash
uv run python examples/hierarchy-gallery/generate_gallery.py \
  --output-folder /tmp/hierarchy-gallery
```

The `build/` directory is generated and ignored. Edit the checked-in data or generator, then rerun
the command to refresh it.
