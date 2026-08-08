# Hierarchical HTML Gallery

This gallery demonstrates the three supported input styles and the theme extension point:

- `delivery-plan.yaml` is rendered by filename with dotted numbering, tracking checkboxes, and
  the packaged `default` theme.
- `incident-review.json` is read as full JSON content and rendered with the packaged `outline` theme.
- an in-memory Python mapping is rendered with the gallery's custom `midnight` theme.

Generate all examples and the gallery index from the repository root:

```bash
uv run python examples/hierarchy-gallery/generate_gallery.py
```

Then open `examples/hierarchy-gallery/build/index.html` in a browser. Each card contains a live,
collapsible preview and a link to the complete self-contained page.

To write somewhere else, pass an explicit destination:

```bash
uv run python examples/hierarchy-gallery/generate_gallery.py \
  --output-folder /tmp/hierarchy-gallery
```

The `build/` directory is generated and ignored. Edit the checked-in data, theme, or generator,
then rerun the command to refresh it.
