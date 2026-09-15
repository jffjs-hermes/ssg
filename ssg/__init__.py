"""ssg - minimal Markdown to HTML static-site generator.

Parses the strict CommonMark 0.31.2 subset defined by SPEC.md in two phases
and renders it to an HTML fragment:

  Phase 1 (blocks)   :mod:`ssg.blocks`   -- block AST (structure first)
  Phase 2 (inlines)  :mod:`ssg.inlines`  -- inline AST for paragraph/heading
  Render             :mod:`ssg.render`   -- (block AST ->) HTML

``render_markdown(markdown)`` is the one-stop entry point: parse a Markdown
string and return the rendered HTML.
"""

from . import blocks, inlines, render
from .render import render_document

__version__ = "0.1.0"


def render_markdown(text):
    """Parse ``text`` (Markdown) and return the rendered HTML string."""
    return render.render(text)


__all__ = ["blocks", "inlines", "render", "render_document",
           "render_markdown"]