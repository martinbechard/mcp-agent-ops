# Hierarchical HTML Gallery

This gallery demonstrates four source and presentation combinations:

- `delivery-plan.yaml` uses document-style labels and a transparent singleton wrapper. Its plan
  entries use dotted numbering, read-only completion markers, and the packaged `default` theme.
  The gallery generator marks items `1` and `2` as complete so the example shows completed and
  open items.
- [`document-outline.md`](data/document-outline.md) provides a reviewable heading outline. Its
  headings and leaf text form the in-memory hierarchy that the renderer displays with dotted
  numbering, no completion markers, and the calm, paper-like packaged `outline` theme.
- `incident-review.json` is read as full JSON content and rendered with the packaged `midnight`
  theme.
- an in-memory Python mapping is rendered with the caller-supplied `blueprint` theme from
  [`themes/blueprint.css`](themes/blueprint.css). Its graph-paper background, drafting colors,
  square controls, and technical typography make the custom styling intentionally non-stock.

Each gallery card includes a **Presentation parameters** callout generated from that example's
rendering configuration. It shows `theme`, `numbering`, and `checkboxes`, plus `themes_folder` when
a caller-supplied theme is used. The callout deliberately excludes source data and file parameters.

Markdown parsing belongs only to this example generator. The public renderer accepts structured
Python data, JSON/YAML content, and JSON/YAML files; it does not accept Markdown directly.
The initial completion state also belongs only to the gallery generator. The public renderer
creates incomplete markers and does not infer completion from source values.

For the complete API and behavior contract, see the
[hierarchical HTML renderer reference](../../docs/reference/hierarchy-html-renderer.md).

Generate all examples and the gallery index from the repository root:

```bash
uv run python examples/hierarchy-gallery/generate_gallery.py
```

Then open `examples/hierarchy-gallery/build/index.html` in a browser. Each card contains a live,
collapsible preview, progressive `1`, `2`, `3`, and `All` level controls, and a link to the
complete self-contained page. Familiar icon controls provide copy, expand-all, and collapse-all
actions. **Copy content** copies only the complete hierarchy as indented plain text. Compare each
preview with its Presentation parameters callout to see which appearance and interaction options
produced it.

To write somewhere else, pass an explicit destination:

```bash
uv run python examples/hierarchy-gallery/generate_gallery.py \
  --output-folder /tmp/hierarchy-gallery
```

The `build/` directory is generated and ignored. Edit the checked-in data or generator, then rerun
the command to refresh it.
