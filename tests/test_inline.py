"""Tests for the ssg inline parser and the full render pipeline.

Phase 2 (inlines) and the block-AST->HTML renderer are exercised together:
every inline fixture in tests/spec_fixtures/ (101-117, owned by this task
per SPEC.md §3) is parsed with the full pipeline (blocks -> inlines -> HTML)
and compared byte-for-byte against its ``expected.html``, which was produced
with commonmark.js 0.31.2 as the reference.

Unit tests below drill into the inline-parser rules the fixtures depend on
(SPEC §1.3, 1.4, 1.5, 1.9 and precedence rule 2) so a regression is located
precisely rather than surfaced only as a fixture diff.
"""

import glob
import os

import pytest

from ssg import blocks, render
from ssg import inlines

SPEC_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "spec_fixtures")

# Inline fixtures owned by this task (SPEC.md §3: 101-117).
INLINE_FIXTURES = sorted([
    "101-emphasis-star",
    "102-emphasis-underscore",
    "103-strong-double",
    "104-strong-and-em",
    "105-emphasis-intraword",
    "106-emphasis-escaped",
    "107-code-span",
    "108-code-span-double-backtick",
    "109-code-span-strip-space",
    "110-code-precedence",
    "111-link-inline",
    "112-link-title",
    "113-link-angle-dest",
    "114-link-with-emphasis",
    "115-nested-links-not-allowed",
    "116-hard-break",
    "117-combined-inlines",
])

# Every inline fixture is a directory under tests/spec_fixtures/.
INLINE_FIXTURE_PATTERN = os.path.join(SPEC_FIXTURES_DIR, "1*-*")


def load(name):
    base = os.path.join(SPEC_FIXTURES_DIR, name)
    with open(os.path.join(base, "input.md")) as f:
        src = f.read()
    with open(os.path.join(base, "expected.html")) as f:
        exp = f.read()
    return src, exp


def on_disk():
    return sorted(os.path.basename(d)
                  for d in glob.glob(INLINE_FIXTURE_PATTERN))


# ---------------------------------------------------------------------------
# Fixture corpus registration
# ---------------------------------------------------------------------------


def test_inline_fixtures_exist():
    """Every inline fixture named in SPEC.md §3 is present on disk."""
    assert on_disk() == INLINE_FIXTURES


def test_every_inline_fixture_has_input_and_expected():
    """Each fixture dir has input.md and expected.html."""
    for name in INLINE_FIXTURES:
        base = os.path.join(SPEC_FIXTURES_DIR, name)
        assert os.path.isfile(os.path.join(base, "input.md")), name
        assert os.path.isfile(os.path.join(base, "expected.html")), name


@pytest.mark.parametrize("name", INLINE_FIXTURES)
def test_inline_fixture_renders_to_expected(name):
    """Full pipeline (blocks -> inlines -> render) matches expected.html."""
    src = load(name)[0]
    assert render.render(src) == load(name)[1]


# ---------------------------------------------------------------------------
# Inline-parser unit tests (SPEC 1.3 / 1.4 / 1.5 / 1.9)
# ---------------------------------------------------------------------------

HTML = {"emph": "em", "strong": "strong"}


def irender(text):
    """Parse ``text`` on its own (as a bare paragraph) and render inner HTML."""
    return render.render(text + "\n").rstrip("\n")


# -- emphasis / strong (1.3) -------------------------------------------

def test_em_strong_types():
    vals = inlines.parse("*x*")
    assert len(vals) == 1 and vals[0].type == "emph"
    vals = inlines.parse("**x**")
    assert vals[0].type == "strong"
    vals = inlines.parse("***x***")
    # triple nest becomes strong wrapping em in the reference implementation
    assert vals[0].type == "emph"
    assert vals[0].children_list()[0].type == "strong"


def test_unescaped_delimiters_are_literal_when_not_flanking():
    assert irender("foo_bar_baz") == "<p>foo_bar_baz</p>"
    assert irender("foo*bar*baz") == "<p>foo<em>bar</em>baz</p>"


def test_backslash_escapes_delimiters():
    assert irender("\\*literal\\*") == "<p>*literal*</p>"
    assert irender("\\_not em\\_") == "<p>_not em_</p>"


# -- inline code (1.4) -------------------------------------------------

def test_code_span():
    assert irender("`code`") == "<p><code>code</code></p>"


def test_code_span_double_backtick():
    assert irender("``a ` b``") == "<p><code>a ` b</code></p>"


def test_code_span_space_stripping():
    assert irender("` code `") == "<p><code>code</code></p>"
    # all-space spans are not stripped
    assert irender("`  `") == "<p><code>  </code></p>"


def test_code_precedes_emphasis():
    assert irender("`*not em*`") == "<p><code>*not em*</code></p>"


# -- links (1.5) --------------------------------------------------------

def test_inline_link():
    assert irender("[foo](/url)") == '<p><a href="/url">foo</a></p>'


def test_link_title():
    assert irender('[foo](/url "title")') == (
        '<p><a href="/url" title="title">foo</a></p>')


def test_link_angle_destination_is_uri_encoded():
    assert irender("[foo](</my url>)") == (
        '<p><a href="/my%20url">foo</a></p>')


def test_emphasis_inside_link():
    assert irender("[*foo*](/url)") == (
        '<p><a href="/url"><em>foo</em></a></p>')


def test_nested_links_not_allowed():
    assert irender("[a [b](c) d](e)") == (
        '<p>[a <a href="c">b</a> d](e)</p>')


def test_unmatched_close_bracket_is_literal():
    assert irender("foo] bar") == "<p>foo] bar</p>"


# -- breaks (1.9) -------------------------------------------------------

def test_softbreak_is_newline():
    assert irender("foo\nbar") == "<p>foo\nbar</p>"


def test_hardbreak_two_spaces():
    assert irender("foo  \nbar") == "<p>foo<br />\nbar</p>"


def test_hardbreak_backslash():
    assert irender("foo\\\nbar") == "<p>foo<br />\nbar</p>"


# -- out-of-scope constructs are literal (1.10, 2) ---------------------

@pytest.mark.parametrize("src,exp", [
    ("<http://a.com>", "<p>&lt;http://a.com&gt;</p>"),   # no autolinks
    ("&amp;", "<p>&amp;amp;</p>"),                        # no entities
    ("![alt](img.png)", "<p>![alt](img.png)</p>"),        # no images
    ("[ref][a]\n\n[a]: /url", "<p>[ref][a]</p>\n<p>[a]: /url</p>"),  # no refs
    ('<em>raw</em>', "<p>&lt;em&gt;raw&lt;/em&gt;</p>"),  # no raw HTML
])
def test_out_of_scope_constructs_are_literal(src, exp):
    assert render.render(src + "\n").rstrip("\n") == exp


# -- HTML escaping -----------------------------------------------------

def test_text_is_html_escaped():
    assert irender("a < b & c > \"d\"") == (
        "<p>a &lt; b &amp; c &gt; &quot;d&quot;</p>")


def test_code_content_is_html_escaped():
    assert irender("`a < b & c`") == "<p><code>a &lt; b &amp; c</code></p>"


# -- integration helpers -------------------------------------------------

def test_blocks_inline_are_raw_but_render_parses_them():
    """Blocks store raw inline text; the renderer parses it (SPEC 2)."""
    doc = blocks.parse("**bold**\n")
    para = next(n for n in doc.walk() if n.type == "paragraph")
    assert para.content == "**bold**"          # phase 1 keeps the source
    assert render.render_document(doc) == "<p><strong>bold</strong></p>\n"