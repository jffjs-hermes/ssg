"""Tests for the ssg block->HTML renderer (:mod:`ssg.render`).

The renderer turns the block AST produced by :mod:`ssg.blocks` (with inline
content parsed by :mod:`ssg.inlines`) into an HTML fragment.  Every fixture in
tests/spec_fixtures/ is graded end-to-end byte-for-byte against its
``expected.html`` (produced with commonmark.js 0.31.2 as the reference).

In addition to the fixture corpus, a handful of direct block-rendering unit
tests cover the HTML-shape decisions the fixture corpus does not isolate on
its own: tight-vs-loose list wrappers, ordered-list ``start``, the
``language-`` class, ``<br />`` hard breaks, and HTML escaping.
"""

import glob
import os
import sys

import pytest

from ssg import blocks
import ssg.render as renderer

SPEC_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "spec_fixtures")


def load(name):
    base = os.path.join(SPEC_FIXTURES_DIR, name)
    with open(os.path.join(base, "input.md")) as f:
        src = f.read()
    with open(os.path.join(base, "expected.html")) as f:
        exp = f.read()
    return src, exp


def all_fixtures():
    """Every fixture directory (block 00* and inline 1*) with input+expected."""
    out = []
    for d in sorted(glob.glob(os.path.join(SPEC_FIXTURES_DIR, "*-*"))):
        if os.path.isdir(d) and all(
                os.path.isfile(os.path.join(d, f))
                for f in ("input.md", "expected.html")):
            out.append(os.path.basename(d))
    return out


@pytest.mark.parametrize("name", all_fixtures())
def test_fixture_renders_to_expected(name):
    """Full pipeline (blocks -> inlines -> render) matches expected.html."""
    src, exp = load(name)
    assert renderer.render(src) == exp


def test_renderer_is_wired_into_package():
    """render_markdown is the one-stop entry point."""
    from ssg import render_markdown
    assert render_markdown("hello") == "<p>hello</p>\n"


# ---------------------------------------------------------------------------
# HTML-shape unit tests (isolated from the corpus)
# ---------------------------------------------------------------------------

def render_md(text):
    return renderer.render(text)


def test_paragraph_with_inline_content():
    assert render_md("*hi* and **there**\n") == (
        "<p><em>hi</em> and <strong>there</strong></p>\n")


def test_heading_levels():
    assert render_md("### Title\n") == "<h3>Title</h3>\n"
    assert render_md("###### deep\n") == "<h6>deep</h6>\n"


def test_softbreak_is_newline():
    assert render_md("line one\nline two\n") == (
        "<p>line one\nline two</p>\n")


def test_hardbreak_two_spaces_and_backslash():
    assert render_md("a  \nb\\\nc\n") == (
        "<p>a<br />\nb<br />\nc</p>\n")


def test_fenced_code_language_class():
    assert render_md("```python\nx\n```\n") == (
        '<pre><code class="language-python">x\n</code></pre>\n')


def test_fenced_code_no_language():
    assert render_md("```\nx\n```\n") == (
        "<pre><code>x\n</code></pre>\n")


def test_fence_content_is_literal_non_inlined():
    # SPEC 2 rule 3: fenced content is never inline-parsed.
    assert "*em*" in render_md("```\n*em*\n```\n")
    assert "<em>" not in render_md("```\n*em*\n```\n")


def test_tight_bullet_list():
    assert render_md("- a\n- b\n") == (
        "<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n")


def test_tight_ordered_list_start():
    assert render_md("3. three\n4. four\n") == (
        '<ol start="3">\n<li>three</li>\n<li>four</li>\n</ol>\n')


def test_ordered_list_omits_start_when_one():
    assert render_md("1. one\n") == (
        "<ol>\n<li>one</li>\n</ol>\n")


def test_loose_list_keeps_paragraphs():
    assert render_md("- one\n\n- two\n") == (
        "<ul>\n<li>\n<p>one</p>\n</li>\n"
        "<li>\n<p>two</p>\n</li>\n</ul>\n")


def test_nested_list():
    assert render_md("- outer\n  - inner\n") == (
        "<ul>\n<li>outer\n<ul>\n<li>inner</li>\n</ul>\n</li>\n</ul>\n")


def test_blockquote():
    assert render_md("> quoted\n") == (
        "<blockquote>\n<p>quoted</p>\n</blockquote>\n")


def test_blockquote_nested():
    assert render_md("> > deep\n") == (
        "<blockquote>\n<blockquote>\n<p>deep</p>\n</blockquote>\n"
        "</blockquote>\n")


def test_html_escaping_of_text():
    assert render_md("a < b & c > \"d\"\n") == (
        '<p>a &lt; b &amp; c &gt; &quot;d&quot;</p>\n')


def test_html_escaping_of_code_content():
    assert render_md("`a < b & c`\n") == (
        "<p><code>a &lt; b &amp; c</code></p>\n")


def test_inline_link_with_title():
    assert render_md('[foo](/url "title")\n') == (
        '<p><a href="/url" title="title">foo</a></p>\n')


def test_em_double_and_strong_flag_in_ast():
    # Emph/strong node types drive the em/strong tags.
    assert render_md("__bold__\n") == "<p><strong>bold</strong></p>\n"
    assert render_md("_em_\n") == "<p><em>em</em></p>\n"


def test_render_document_accepts_block_ast():
    doc = blocks.parse("# title\n")
    assert renderer.render_document(doc) == "<h1>title</h1>\n"


# ---------------------------------------------------------------------------
# Optional Pygments syntax highlighting (highlight= keyword)
# ---------------------------------------------------------------------------

def test_highlight_disabled_by_default():
    """highlight defaults to False -> byte-identical to the legacy renderer."""
    src = "```python\nx = 1\n```\n"
    no_hl = renderer.render(src, highlight=False)
    assert renderer.render(src) == no_hl          # default arg matches explicit False
    assert "<span class=" not in no_hl            # and emits no token spans


def test_highlight_enabled_emits_token_spans_inside_code():
    """With highlight=True the outer <pre><code class=...> contract is kept
    and Pygments token spans go inside <code>."""
    out = renderer.render("```python\nx = 1\n```\n", highlight=True)
    assert out.startswith('<pre><code class="language-python">')
    assert out.endswith("</code></pre>\n")
    inner = out[len('<pre><code class="language-python">'):-len("</code></pre>\n")]
    assert '<span class="' in inner               # spans live between <code></code>
    assert inner.endswith("\n")                   # content trailing newline kept


def test_highlight_unknown_language_falls_back_to_literal():
    """Unknown lexer -> same escaped-literal output as the legacy path, no raise."""
    out = renderer.render("```doesnotexist\nx < y &\n```\n", highlight=True)
    assert '<span' not in out
    assert out == ('<pre><code class="language-doesnotexist">'
                   "x &lt; y &amp;\n</code></pre>\n")


def test_highlight_no_language_falls_back_to_literal():
    """No info string -> fallback unchanged (no class, no spans)."""
    out = renderer.render("```\nx < b\n```\n", highlight=True)
    assert '<span' not in out
    assert out == "<pre><code>x &lt; b\n</code></pre>\n"


def test_highlight_escapes_untrusted_fence_content():
    """Fence content is untrusted: HTML chars must be escaped in the output."""
    src = "```python\n<script>alert(1)</script> & \"q\"\n```\n"
    out = renderer.render(src, highlight=True)
    assert "&lt;" in out and "&amp;" in out
    assert "<script>" not in out
    assert '<span class="' in out                 # Pygments path still active


def test_highlight_missing_pygments_does_not_raise(monkeypatch):
    """Even without Pygments importable, highlight=True never raises."""
    monkeypatch.setitem(sys.modules, "pygments", None)
    out = renderer.render("```python\nx < y\n```\n", highlight=True)
    assert '<span' not in out
    assert out == '<pre><code class="language-python">x &lt; y\n</code></pre>\n'


def test_render_document_highlight_wiring():
    """render_document(doc, highlight=True) honours the flag on the AST path."""
    doc = blocks.parse("```python\nx = 1\n```\n")
    out = renderer.render_document(doc, highlight=True)
    assert out.startswith('<pre><code class="language-python">')
    assert '<span class="' in out
    assert '<span class="' not in renderer.render_document(doc)  # default off
