"""Tests for the ssg block parser (phase 1).

Every fixture in tests/spec_fixtures/ whose corpus is owned by the BLOCK
parser task (001-022 per SPEC.md §3) is parsed and its block AST compared
against the expected structure recorded here.

The expected structures were derived and cross-validated against commonmark.js
0.31.2 block-parsing semantics (SPEC.md names it as the model).  Inline
content of paragraphs/headings stays raw (em/strong/links/code are phase 2),
so paragraph/heading ``content`` is the verbatim inline source including any
markup markers — that is intentional and matches SPEC §2 ("block structure
first, inlines second").
"""

import glob
import os

import pytest

from ssg import blocks

SPEC_FIXTURES_DIR = os.path.join(
    os.path.dirname(__file__), "spec_fixtures")

# Block fixtures owned by this task.  (Inline fixtures 101-117 belong to the
# inline-parser task and are not exercised here.)
BLOCK_FIXTURES = sorted(
    os.path.basename(d)
    for d in glob.glob(os.path.join(SPEC_FIXTURES_DIR, "0*-*"))
)


def load(name):
    base = os.path.join(SPEC_FIXTURES_DIR, name)
    with open(os.path.join(base, "input.md"), "r") as f:
        src = f.read()
    exp_html = None
    exp_path = os.path.join(base, "expected.html")
    if os.path.exists(exp_path):
        with open(exp_path, "r") as f:
            exp_html = f.read()
    return src, exp_html


def sig(node):
    """Compact canonical representation of a block AST node (recursive)."""
    d = {"t": node.type}
    if node.type == "heading":
        d["level"] = node.level
        d["c"] = node.content
    elif node.type == "paragraph":
        d["c"] = node.content
    elif node.type == "code_block":
        d["lang"] = node.language
        d["c"] = node.content
    elif node.type == "list":
        ld = node.list_data
        d["list"] = {
            "type": ld["type"],
            "start": ld["start"],
            "delimiter": ld["delimiter"],
            "bulletChar": ld["bulletChar"],
            "tight": ld["tight"],
        }
    if node.children:
        d["children"] = [sig(c) for c in node.children]
    return d


# ---------------------------------------------------------------------------
# Expected block ASTs per fixture (verified against commonmark.js semantics).
# ---------------------------------------------------------------------------

EXPECTED = {
    "001-para-simple": {"t": "document", "children": [{
        "t": "paragraph", "c": "Hello, world."}]},
    "002-para-multiline": {"t": "document", "children": [{
        "t": "paragraph", "c": "foo\nbar"}]},
    "003-heading-levels": {"t": "document", "children": [
        {"t": "heading", "level": 1, "c": "h1"},
        {"t": "heading", "level": 2, "c": "h2"},
        {"t": "heading", "level": 3, "c": "h3"},
        {"t": "heading", "level": 4, "c": "h4"},
        {"t": "heading", "level": 5, "c": "h5"},
        {"t": "heading", "level": 6, "c": "h6"}]},
    "004-heading-trailing-hashes": {"t": "document", "children": [
        {"t": "heading", "level": 2, "c": "foo"},
        {"t": "heading", "level": 1, "c": "bar"},
        {"t": "heading", "level": 3, "c": "baz###"}]},
    "005-heading-no-space": {"t": "document", "children": [{
        "t": "paragraph", "c": "#5 bolt"}]},
    "006-heading-interrupts-para": {"t": "document", "children": [
        {"t": "paragraph", "c": "foo"},
        {"t": "heading", "level": 1, "c": "bar"},
        {"t": "paragraph", "c": "baz"}]},
    "007-fence-backtick": {"t": "document", "children": [{
        "t": "code_block", "lang": "python", "c": "x = 1\nprint(x)\n"}]},
    "008-fence-tilde": {"t": "document", "children": [{
        "t": "code_block", "lang": None, "c": "plain text\n"}]},
    "009-fence-unclosed": {"t": "document", "children": [{
        "t": "code_block", "lang": None, "c": "code to end\n"}]},
    "010-fence-not-inline-parsed": {"t": "document", "children": [{
        "t": "code_block", "lang": None,
        "c": "*not emphasis*\n`not code`\n"}]},
    "011-list-bullet-tight": {"t": "document", "children": [{
        "t": "list",
        "list": {"type": "bullet", "start": None, "delimiter": None,
                 "bulletChar": "-", "tight": True},
        "children": [
            {"t": "item", "children": [{"t": "paragraph", "c": "alpha"}]},
            {"t": "item", "children": [{"t": "paragraph", "c": "beta"}]},
            {"t": "item", "children": [{"t": "paragraph", "c": "gamma"}]},
        ]}]},
    "012-list-ordered": {"t": "document", "children": [{
        "t": "list",
        "list": {"type": "ordered", "start": 3, "delimiter": ".",
                 "bulletChar": None, "tight": True},
        "children": [
            {"t": "item", "children": [{"t": "paragraph", "c": "three"}]},
            {"t": "item", "children": [{"t": "paragraph", "c": "four"}]},
        ]}]},
    "013-list-loose": {"t": "document", "children": [{
        "t": "list",
        "list": {"type": "bullet", "start": None, "delimiter": None,
                 "bulletChar": "-", "tight": False},
        "children": [
            {"t": "item", "children": [{"t": "paragraph", "c": "one"}]},
            {"t": "item", "children": [{"t": "paragraph", "c": "two"}]},
        ]}]},
    "014-list-nested": {"t": "document", "children": [{
        "t": "list",
        "list": {"type": "bullet", "start": None, "delimiter": None,
                 "bulletChar": "-", "tight": True},
        "children": [{
            "t": "item", "children": [
                {"t": "paragraph", "c": "outer"},
                {"t": "list",
                 "list": {"type": "bullet", "start": None,
                          "delimiter": None, "bulletChar": "-",
                          "tight": True},
                 "children": [
                     {"t": "item",
                      "children": [{"t": "paragraph", "c": "inner"}]},
                 ]},
            ]}]}]},
    "015-list-para-continuation": {"t": "document", "children": [{
        "t": "list",
        "list": {"type": "bullet", "start": None, "delimiter": None,
                 "bulletChar": "-", "tight": True},
        "children": [
            {"t": "item",
             "children": [{"t": "paragraph", "c": "item\nwrapped text"}]},
        ]}]},
    "016-list-mixed-markers": {"t": "document", "children": [
        {"t": "list",
         "list": {"type": "bullet", "start": None, "delimiter": None,
                  "bulletChar": "-", "tight": True},
         "children": [{"t": "item",
                       "children": [{"t": "paragraph", "c": "dash"}]}]},
        {"t": "list",
         "list": {"type": "bullet", "start": None, "delimiter": None,
                  "bulletChar": "*", "tight": True},
         "children": [{"t": "item",
                       "children": [{"t": "paragraph", "c": "star"}]}]}]},
    "017-blockquote-simple": {"t": "document", "children": [{
        "t": "block_quote",
        "children": [{"t": "paragraph", "c": "quoted text"}]}]},
    "018-blockquote-lazy": {"t": "document", "children": [{
        "t": "block_quote",
        "children": [{"t": "paragraph", "c": "quoted\nlazy continuation"}]}]},
    "019-blockquote-nested": {"t": "document", "children": [{
        "t": "block_quote",
        "children": [{
            "t": "block_quote",
            "children": [{"t": "paragraph", "c": "depth two"}]}]}]},
    "020-blockquote-interrupts-para": {"t": "document", "children": [
        {"t": "paragraph", "c": "para text"},
        {"t": "block_quote",
         "children": [{"t": "paragraph", "c": "quote"}]}]},
    "021-blank-line-separation": {"t": "document", "children": [
        {"t": "paragraph", "c": "one"},
        {"t": "paragraph", "c": "two"}]},
    "022-mixed-document": {"t": "document", "children": [
        {"t": "heading", "level": 1, "c": "Title"},
        {"t": "paragraph", "c": "A paragraph with **strong** and *em*."},
        {"t": "code_block", "lang": "python", "c": "code = 1\n"},
        {"t": "list",
         "list": {"type": "bullet", "start": None, "delimiter": None,
                  "bulletChar": "-", "tight": True},
         "children": [
             {"t": "item", "children": [{"t": "paragraph", "c": "first"}]},
             {"t": "item", "children": [{"t": "paragraph", "c": "second"}]},
         ]},
        {"t": "block_quote",
         "children": [{"t": "paragraph", "c": "quoted"}]}]},
}


# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fixture_map():
    """{fixture_name: (input_md, expected_html_or_None)} for block fixtures."""
    return {name: load(name) for name in BLOCK_FIXTURES}


def test_block_fixtures_exist(fixture_map):
    """Every block fixture named in the SPEC corpus is present on disk."""
    assert set(fixture_map) == set(EXPECTED) == set(BLOCK_FIXTURES)


def test_every_block_fixture_hooks_to_expected_ast():
    """No block fixture is missing a recorded expected AST."""
    missing = set(BLOCK_FIXTURES) - set(EXPECTED)
    assert not missing, "block fixtures missing expected AST: %s" % sorted(missing)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_block_ast(name):
    """Parse the fixture's input.md and compare the block AST."""
    src, _ = load(name)
    doc = blocks.parse(src)
    assert isinstance(doc, blocks.Node)
    assert doc.type == "document"
    assert sig(doc) == EXPECTED[name]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_document_closed_and_unlinked(name):
    """Basic tree invariants: doc is closed, no leftover open blocks."""
    src, _ = load(name)
    doc = blocks.parse(src)
    assert doc._open is False
    for node in doc.walk():
        for child in node.children:
            assert child._parent is node


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_edit_each_fixture_does_not_crash(name):
    """Parse a slightly edited variant (extra trailing newline) safely."""
    src, _ = load(name)
    doc = blocks.parse(src + "\n\n")
    assert doc.type == "document"