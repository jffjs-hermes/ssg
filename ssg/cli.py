"""Command-line interface for ssg.

Exposes two commands::

    python -m ssg build <in> <out>
    python -m ssg serve <in> [--port PORT] [--host HOST] [--out OUT] [--no-reload]

``build`` walks ``<in>`` recursively, rendering every ``.md`` file to a matching
``<path>.html`` under ``<out>`` and copying every non-Markdown file verbatim
(static assets, preserving their relative paths).  ``serve`` composes ``build``
into a live development server with optional hot reload (see
:mod:`ssg.serve`).
"""

import argparse
import os
import re
import shutil
import sys

from ssg import blocks, render
from ssg import serve as serve_mod

__all__ = ["build", "build_file", "page_title", "serve", "main"]

_HTML_DOC = (
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    "<title>{title}</title>\n"
    "</head>\n"
    "<body>\n"
    "{body}"
    "</body>\n"
    "</html>\n"
)


def _escape(text):
    """HTML-escape text content (mirrors the renderer's escaping)."""
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _flatten_inlines(source):
    """Flatten inline Markdown ``source`` to plain text (no HTML tags)."""
    html = render.render(source.rstrip("\n") + "\n")
    return re.sub(r"<[^>]+>", "", html).replace("\n", " ").strip()


def page_title(doc):
    """The page title: the first top-level heading's flattened text.

    ``doc`` is a block AST from :func:`ssg.blocks.parse`. Returns an empty
    string when the document has no heading.
    """
    for child in doc.children:
        if child.type == "heading":
            return _flatten_inlines(child.content)
    return ""


def build_file(md_path, html_path, highlight=False):
    """Render one Markdown file to a full HTML page at ``html_path``.

    ``highlight`` is passed through to :func:`ssg.render.render`; when True,
    fenced code blocks matching a Pygments lexer get syntax-highlighted token
    spans (see :func:`ssg.render.render_document`).
    """
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    doc = blocks.parse(text)
    title = page_title(doc) or os.path.splitext(os.path.basename(md_path))[0]
    body = render.render(text, highlight=highlight)
    page = _HTML_DOC.format(title=_escape(title), body=body)
    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(page)
    return html_path


def build(in_dir, out_dir, highlight=False):
    """Build a static site: render Markdown pages and copy static assets.

    Walks ``in_dir``; every ``*.md`` file becomes ``{out_dir}/{rel}.html`` and
    every other file is copied byte-for-byte to ``{out_dir}/{rel}`` (relative
    paths preserved).  ``highlight`` is passed through to
    :func:`build_file` for optional Pygments fenced-code highlighting.
    Returns a summary dict.
    """
    in_dir = os.path.abspath(in_dir)
    out_dir = os.path.abspath(out_dir)
    if not os.path.isdir(in_dir):
        raise SystemExit("error: input directory not found: %s" % in_dir)
    os.makedirs(out_dir, exist_ok=True)

    pages = 0
    assets = 0
    for root, dirs, files in os.walk(in_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in files:
            src = os.path.join(root, name)
            rel = os.path.relpath(src, in_dir)
            dst = os.path.join(out_dir, rel)
            if name.lower().endswith(".md"):
                build_file(src, os.path.splitext(dst)[0] + ".html",
                           highlight=highlight)
                pages += 1
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                assets += 1
    return {"pages": pages, "assets": assets, "out_dir": out_dir}


def _build_cmd(args):
    summary = build(args.input, args.output, highlight=args.highlight)
    print("Built %d page(s) and copied %d asset(s) to %s" % (
        summary["pages"], summary["assets"], summary["out_dir"]))


def serve(input_dir, host="127.0.0.1", port=8000, out_dir=None, no_reload=False):
    """Run a development HTTP server over a built copy of ``input_dir``.

    Thin wrapper over :func:`ssg.serve.serve` with the CLI's defaults.  Blocks
    until the server is shut down.  See the module docstring for the full
    hot-reload semantics.
    """
    return serve_mod.serve(input_dir, host=host, port=port,
                           out_dir=out_dir, no_reload=no_reload)


def _serve_cmd(args):
    serve(args.input, host=args.host, port=args.port,
          out_dir=args.output, no_reload=args.no_reload)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m ssg",
        description="Minimal Markdown to HTML static-site generator.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="render a Markdown site")
    p_build.add_argument("input", help="input directory of Markdown + assets")
    p_build.add_argument("output", help="output directory to write the site to")
    p_build.add_argument(
        "--highlight", action="store_true",
        help="syntax-highlight fenced code blocks with Pygments (optional)")
    p_build.set_defaults(func=_build_cmd)

    p_serve = sub.add_parser("serve",
                             help="run a development server with hot reload")
    p_serve.add_argument("input", help="input directory of Markdown + assets")
    p_serve.add_argument("--port", type=int, default=8000,
                         help="port to listen on (default: 8000)")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="host/interface to bind (default: 127.0.0.1)")
    p_serve.add_argument("--out", dest="output", default=None,
                         help="serve output dir (default: a fresh temp dir)")
    p_serve.add_argument("--no-reload", action="store_true",
                         help="serve statically; disable watching + reload")
    p_serve.set_defaults(func=_serve_cmd)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
