# ssg

Minimal Markdown → HTML static-site generator in Python.

Built by the Hermes bot dev team (lead / builder / reviewer / researcher) as a
first shakedown of a multi-bot software-development pipeline.

**Supported Markdown:** a strict CommonMark 0.31.2 subset — ATX headings,
paragraphs, emphasis/strong, inline code, inline links, fenced code blocks,
lists, blockquotes, hard/soft breaks. See `SPEC.md` for the exact feature set,
out-of-scope list, and the 39-fixture corpus.

## Setup

Requirements: **Python 3.10+** (developed on 3.13). No system packages needed;
everything installs into a project-local virtualenv.

```bash
python3 -m venv .venv                       # isolated, one-time
.venv/bin/pip install pytest                # only runtime dep for tests; the
                                            # generator itself is stdlib-only
```

> The bot workers create their own virtualenv inside each card's worktree and
> install pytest there, so they don't depend on a global install. The command
> above is yours to run the suite from the repo root.

## Run the tests

```bash
.venv/bin/python -m pytest -q               # 175 tests, stdlib-only generator
```

## Use it

```bash
.venv/bin/python -m ssg build example dist  # compile example/ -> dist/
```

`build <in> <out>` walks a markdown directory, renders each page to HTML,
copying static assets (e.g. `style.css`) alongside. Run it over `example/` to
reproduce the site already shipped under `dist/`.

## Project layout

```
ssg/
  blocks.py    block-level parser (SPEC.md feature set -> block AST)
  inlines.py   inline parser (emphasis, strong, code, links)
  render.py    AST -> HTML
  cli.py       "python -m ssg build <in> <out>" entrypoint
tests/
  test_blocks.py / test_inline.py / test_render.py   unit tests per module
  test_cli_e2e.py                                    end-to-end build test
  spec_fixtures/   input.md + expected.html fixtures from SPEC.md
example/     sample blog (markdown source)      dist/   built output
SPEC.md      the supported Markdown subset + fixture corpus spec
```