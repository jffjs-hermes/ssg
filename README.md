# ssg

Minimal Markdown to HTML static-site generator in Python.
Built by the Hermes bot dev team (lead / builder / reviewer / researcher).

Usage: `python -m ssg build <in> <out>`

Walks `<in>` recursively, turns every `.md` file into a matching `<path>.html`
page under `<out>` (page title taken from the first heading), and copies every
non-Markdown file through verbatim as a static asset.

```
python -m ssg build example dist
```

Renders the included `example/` site (4 posts + a welcome page and two static
assets) into `dist/`. The repository includes the generated `dist/` snapshot;
rerun the command after changing anything under `example/`.

## Layout

- `ssg/blocks.py` — CommonMark-style block parser (phase 1)
- `ssg/inlines.py` — inline parser (phase 2)
- `ssg/render.py` — block AST → HTML fragment renderer
- `ssg/cli.py` + `ssg/__main__.py` — `python -m ssg build` command
- `example/` — the sample site
- `tests/` — pytest suite (fixture corpus + unit + CLI end-to-end)

## Tests

```
python -m pytest tests/ -q
```