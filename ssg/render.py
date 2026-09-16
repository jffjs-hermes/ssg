"""HTML rendering for the ssg Markdown subset.

Turns a block AST produced by :mod:`ssg.blocks` into an HTML fragment,
following the default commonmark.js HTML renderer (the exact format the SPEC
fixture corpus ``expected.html`` files are written in): soft breaks render as
``\\n``, hard breaks as ``<br />\\n``, fenced code blocks carry a ``language-``
class, tight lists suppress paragraph tags, ordered lists emit ``start=`` when
not 1, and all text is HTML-escaped.

Inline content of paragraphs and headings is not stored on the block yet: it
is parsed on demand from the raw ``content`` text by :mod:`ssg.inlines` (phase
2) at render time.
"""

from . import blocks, inlines

__all__ = ["render", "render_document"]


class _Renderer:
    """Port of commonmark.js render/renderer.js + render/html.js (default).

    The buffer tracks ``last`` (the most recently emitted literal) so that
    ``cr()`` only writes a newline when the output does not already end in
    one.  That is what produces the compact, newline-delimited fragments the
    fixture corpus expects (no leading blank line, one trailing newline).
    """

    def __init__(self, highlight=False):
        self.buf = []
        self.last = "\n"
        self.highlight = highlight
        self._lexers = None

    # -- low-level output ----------------------------------------------
    def lit(self, s):
        self.buf.append(s)
        self.last = s

    def cr(self):
        if self.last != "\n":
            self.lit("\n")

    @staticmethod
    def _esc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))

    def out(self, s):
        self.lit(self._esc(s))

    def tag(self, name, attrs=(), selfclosing=False):
        if selfclosing:
            self.lit("<%s%s />" % (name, self._attrs(attrs)))
        else:
            self.lit("<%s%s>" % (name, self._attrs(attrs)))

    @staticmethod
    def _attrs(attrs):
        return "".join(' %s="%s"' % (k, v) for k, v in attrs)

    # -- inline content -------------------------------------------------
    def render_inlines(self, nodes):
        """Render a *list* of top-level inline nodes (from ``inlines.parse``).

        All top-level nodes are siblings in one ``_next`` chain (each
        paragraph/heading is a single chain), so rendering the head already
        walks the whole list.
        """
        if nodes:
            self._render_chain(nodes[0])

    def _render_chain(self, node):
        while node is not None:
            t = node.type
            if t == "text":
                self.out(node.literal)
            elif t == "softbreak":
                self.cr()
            elif t == "linebreak":
                self.tag("br", selfclosing=True)
                self.cr()
            elif t == "code":
                self.tag("code")
                self.out(node.literal)
                self.tag("/code")
            elif t in ("emph", "strong"):
                name = "em" if t == "emph" else "strong"
                self.tag(name)
                if node._first_child is not None:
                    self._render_chain(node._first_child)
                self.tag("/" + name)
            elif t == "link":
                attrs = [("href", self._esc(node.destination))]
                if node.title:
                    attrs.append(("title", self._esc(node.title)))
                self.tag("a", attrs)
                if node._first_child is not None:
                    self._render_chain(node._first_child)
                self.tag("/a")
            node = node._next

    # -- optional Pygments highlighting -----------------------------------
    def _pygments(self):
        """Import Pygments on first use (lazy, so the CLI stays stdlib-only
        unless ``highlight=True``).  Returns a 4-tuple of the pygments pieces,
        or ``None`` when Pygments is not installed so callers fall back."""
        if self._lexers is not None:
            return self._lexers
        try:
            from pygments import highlight as _hl
            from pygments.formatters import HtmlFormatter
            from pygments.lexers import ClassNotFound, get_lexer_by_name
        except ImportError:
            self._lexers = None
            return None
        self._lexers = (_hl, get_lexer_by_name, ClassNotFound,
                        HtmlFormatter(nowrap=True))
        return self._lexers

    def _highlight_code(self, lang, content):
        """Highlight ``content`` (language ``lang``) to token HTML.

        Returns the Pygments output (already HTML-escaped) or ``None`` when
        Pygments is unavailable or the lexer is unknown, in which case the
        caller emits the escaped literal.  Never raises.  Fence content is
        treated as untrusted: only Pygments' own escaped output is trusted.
        """
        pkgs = self._pygments()
        if pkgs is None:
            return None
        _hl, get_lexer_by_name, ClassNotFound, formatter = pkgs
        try:
            lexer = get_lexer_by_name(lang)
        except ClassNotFound:
            return None
        return _hl(content, lexer, formatter)

    # -- blocks ----------------------------------------------------------
    def _language_class(self, lang):
        if lang.startswith("language-"):
            return lang
        return "language-" + lang

    def render_block(self, node):
        t = node.type
        if t == "document":
            for c in node.children:
                self.render_block(c)
        elif t == "paragraph":
            # tight-list paragraphs suppress the <p> wrapper entirely
            if self._in_tight_list(node):
                self.render_inlines(inlines.parse(node.content))
            else:
                self.cr()
                self.tag("p")
                self.render_inlines(inlines.parse(node.content))
                self.tag("/p")
                self.cr()
        elif t == "heading":
            self.cr()
            self.tag("h%d" % node.level)
            self.render_inlines(inlines.parse(node.content))
            self.tag("/h%d" % node.level)
            self.cr()
        elif t == "code_block":
            attrs = ()
            if node.language:
                attrs = (("class", self._esc(self._language_class(node.language))),)
            self.cr()
            self.tag("pre")
            self.tag("code", attrs)
            highlighted = None
            if self.highlight and node.language:
                highlighted = self._highlight_code(node.language, node.content)
            if highlighted is not None:
                self.lit(highlighted)      # Pygments HTML is pre-escaped
            else:
                self.out(node.content)     # escaped-literal fallback
            self.tag("/code")
            self.tag("/pre")
            self.cr()
        elif t == "list":
            tagname = "ul" if node.list_data["type"] == "bullet" else "ol"
            attrs = []
            start = node.list_data.get("start")
            if start is not None and start != 1:
                attrs.append(("start", str(start)))
            self.cr()
            self.tag(tagname, attrs)
            self.cr()
            for c in node.children:
                self.render_block(c)
            self.cr()
            self.tag("/" + tagname)
            self.cr()
        elif t == "item":
            self.tag("li")
            for c in node.children:
                self.render_block(c)
            self.tag("/li")
            self.cr()
        elif t == "block_quote":
            self.cr()
            self.tag("blockquote")
            self.cr()
            for c in node.children:
                self.render_block(c)
            self.cr()
            self.tag("/blockquote")
            self.cr()

    @staticmethod
    def _in_tight_list(node):
        """True when ``node`` is a paragraph directly inside a tight list item."""
        gp = node._parent and node._parent._parent
        return (node._parent is not None and node._parent.type == "item"
                and gp is not None and gp.type == "list"
                and gp.list_data.get("tight"))


def render_document(doc, highlight=False):
    """Render a parsed block AST (:class:`ssg.blocks.Node`) to an HTML string.

    When ``highlight=True``, fenced code blocks whose language matches a
    Pygments lexer are emitted with syntax-highlighting token spans inside the
    existing ``<pre><code class=\"language-…\">…</code></pre>`` container (via
    ``HtmlFormatter(nowrap=True)``).  Unknown/missing lexers and a missing
    Pygments install fall back to the escaped literal; the default ``False``
    keeps output byte-identical to the previous release.
    """
    r = _Renderer(highlight)
    r.render_block(doc)
    return "".join(r.buf)


def render(text, highlight=False):
    """Parse Markdown ``text`` and render the whole document to HTML."""
    return render_document(blocks.parse(text), highlight=highlight)