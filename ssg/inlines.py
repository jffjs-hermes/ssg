"""Inline parser (phase 2) for the ssg Markdown subset.

Parses the inline content of paragraphs and headings (raw text with
``\\n``-joined lines, as produced by :mod:`ssg.blocks`) into a linked list of
inline AST nodes, following the strict CommonMark 0.31.2 subset described in
SPEC.md (rules 1.3, 1.4, 1.5, 1.9 and precedence rule 2).

This is a faithful Python port of commonmark.js's ``inlines.js`` (BSD-2;
SPEC.md names it as the model), restricted to the SPEC subset: autolinks,
raw HTML inlines, entities, images, reference links and smart quotes are all
out of scope and fall through to literal text, and the ``openers_bottom``
modulo-3 optimization of ``processEmphasis`` is deliberately omitted (SPEC
§1.3 permits this: correctness on normal documents is required, linear-time
worst case is not).

Inline node types:

  text         literal text (escaped at render time)
  softbreak    single newline between lines
  linebreak    hard line break (2+ trailing spaces, or trailing backslash)
  emph         emphasis (``*foo*`` / ``_foo_``)
  strong       strong emphasis (``**foo**`` / ``__foo__``)
  code         inline code span (content already newline-collapsed/stripped)
  link         inline link; ``destination`` and optional ``title`` + children
"""

import re

__all__ = ["Node", "parse"]

# ---------------------------------------------------------------------------
# character classes and regexes (ported from commonmark.js lib/common.js and
# lib/inlines.js; subset only)
# ---------------------------------------------------------------------------

# ESCAPABLE = all ASCII punctuation.  This is exactly string.punctuation.
_ESCAPABLE = frozenset('!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~')
_PUNCT = _ESCAPABLE  # rePunctuation truncated to ASCII (subset)


def _is_ws(ch):
    """Whitespace per reUnicodeWhitespaceChar (\\s)."""
    return ch is not None and ch.isspace()


def _is_punct(ch):
    return ch is not None and ch in _PUNCT


# reTicksHere / reTicks
_RE_TICKS_HERE = re.compile(r"^`+")
_RE_TICKS = re.compile(r"`+")

# reEscapable
_RE_ESCAPABLE = re.compile(
    r"\\([!\"#$%&'()*+,./:;<=>?@\[\]^_`{|}~-])")

# reInitialSpace
_RE_INITIAL_SPACE = re.compile(r"^ *")

# reMain: a run of non-special characters (subset: !, <, &, ', " also treated
# as literal but they are excluded here so the special handlers see them).
_RE_MAIN = re.compile(r'[^\n`\[\]\\!<&*_\'"]+')

# reSpnl
_RE_SPNL = re.compile(r" *(?:\n *)?")

# reLinkDestinationBraces
_RE_LINK_DEST_BRACES = re.compile(r"^(?:<(?:[^<>\n\\\x00]|\\.)*>)")

# reLinkTitle (subset: the three quote styles, with backslash escapes).
_ESCAPED_CHAR = r"\\(?:[!\"#$%&'()*+,./:;<=>?@\[\]^_`{|}~-])"
_TITLE_DQ = '"(?:%s|\\\\[^\\\\]|[^\\\\"\\x00])*"' % _ESCAPED_CHAR
_TITLE_SQ = "'(?:%s|\\\\[^\\\\]|[^\\\\'\\x00])*'" % _ESCAPED_CHAR
_TITLE_PA = r"\((?:%s|\\\\[^\\\\]|[^\\\\()\x00])*\)" % _ESCAPED_CHAR
_RE_LINK_TITLE = re.compile(
    "^(?:" + _TITLE_DQ + "|" + _TITLE_SQ + "|" + _TITLE_PA + ")")

# ---------------------------------------------------------------------------
# inline node
# ---------------------------------------------------------------------------


class Node:
    """A node in the inline AST (doubly linked list; children via first/last)."""

    __slots__ = ("type", "literal", "destination", "title",
                 "_parent", "_first_child", "_last_child", "_prev", "_next")

    def __init__(self, type_, literal=None, destination=None, title=None):
        self.type = type_
        self.literal = literal          # text / code content
        self.destination = destination  # link destination (normalized/encoded)
        self.title = title              # link title ('' or None when absent)
        self._parent = None
        self._first_child = None
        self._last_child = None
        self._prev = None
        self._next = None

    # -- linked-list operations (port of commonmark.js Node.prototype) ----
    def append_child(self, child):
        child.unlink()
        child._parent = self
        if self._last_child:
            self._last_child._next = child
            child._prev = self._last_child
            self._last_child = child
        else:
            self._first_child = child
            self._last_child = child

    def unlink(self):
        if self._prev:
            self._prev._next = self._next
        elif self._parent:
            self._parent._first_child = self._next
        if self._next:
            self._next._prev = self._prev
        elif self._parent:
            self._parent._last_child = self._prev
        self._parent = None
        self._next = None
        self._prev = None

    def insert_after(self, sibling):
        sibling.unlink()
        sibling._next = self._next
        if sibling._next:
            sibling._next._prev = sibling
        sibling._prev = self
        self._next = sibling
        sibling._parent = self._parent
        if sibling._next is None:
            sibling._parent._last_child = sibling

    def children_list(self):
        """Ordered list of direct children (handy for tests/debug)."""
        out = []
        n = self._first_child
        while n is not None:
            out.append(n)
            n = n._next
        return out


# ---------------------------------------------------------------------------
# small helpers (common.js)
# ---------------------------------------------------------------------------


def unescape_string(s):
    """Undo backslash escapes (entities are out of scope for the subset)."""
    if "\\" in s:
        return _RE_ESCAPABLE.sub(r"\1", s)
    return s


# mdurl encode(defaultChars = ";/?:@&=+$,-_.!~*'()#") ported to Python.
_URI_KEEP = frozenset(";/?:@&=+$,-_.!~*'()#")
_HEX2 = re.compile(r"^[0-9a-f]{2}$", re.IGNORECASE)


def _encode_uri(uri):
    out = []
    i, n = 0, len(uri)
    while i < n:
        code = ord(uri[i])
        if code == 0x25 and i + 2 < n and _HEX2.match(uri[i + 1:i + 3]):
            out.append(uri[i:i + 3])  # keep an already-encoded sequence
            i += 3
            continue
        if code < 128:
            ch = uri[i]
            if ch.isalnum() or ch in _URI_KEEP:
                out.append(ch)
            else:
                out.append("%%%02X" % code)
            i += 1
        else:
            for b in uri[i].encode("utf-8"):
                out.append("%%%02X" % b)
            i += 1
    return "".join(out)


def normalize_uri(uri):
    return _encode_uri(uri)


def previous_char(subject, pos):
    if pos == 0:
        return "\n"
    return subject[pos - 1]


def _trim_ascii_ws(s):
    start, end = 0, len(s)
    while start < end and s[start] in " \t\n\r":
        start += 1
    while end > start and s[end - 1] in " \t\n\r":
        end -= 1
    return s[start:end]


# ---------------------------------------------------------------------------
# delimiter / bracket stack entries
# ---------------------------------------------------------------------------


class _Delim:
    __slots__ = ("cc", "numdelims", "origdelims", "node",
                 "previous", "next", "can_open", "can_close")

    def __init__(self, cc, numdelims, node, can_open, can_close):
        self.cc = cc
        self.numdelims = numdelims
        self.origdelims = numdelims
        self.node = node
        self.previous = None
        self.next = None
        self.can_open = can_open
        self.can_close = can_close


class _Bracket:
    __slots__ = ("node", "previous", "previous_delimiter", "index",
                 "image", "active", "bracket_after")

    def __init__(self, node, previous, previous_delimiter, index):
        self.node = node
        self.previous = previous
        self.previous_delimiter = previous_delimiter
        self.index = index
        self.image = False
        self.active = True
        self.bracket_after = False


# ---------------------------------------------------------------------------
# inline parser
# ---------------------------------------------------------------------------


class InlineParser:
    """A subject + position that builds a linked list of inline nodes."""

    def __init__(self):
        self.subject = ""
        self.pos = 0
        self.delimiters = None   # top of delimiter stack
        self.brackets = None     # top of bracket stack
        self.block = None        # temporary root we append to

    # -- subject helpers ------------------------------------------------
    def at(self, i):
        return self.subject[i] if 0 <= i < len(self.subject) else None

    def peek(self):
        return self.subject[self.pos] if self.pos < len(self.subject) else None

    def match(self, regex):
        # Slice like commonmark.js's `re.exec(this.subject.slice(this.pos))`:
        # anchored `^` patterns must match at this.pos, so we match against a
        # slice (re.match with a pos argument would ignore `^`).
        m = regex.match(self.subject[self.pos:])
        if m is None:
            return None
        self.pos += m.end()
        return m.group(0)

    def _text(self, s):
        return Node("text", literal=s)

    def _append(self, node):
        self.block.append_child(node)

    # -- delimiter stack ------------------------------------------------
    def _push_delimiter(self, cc, numdelims, node, can_open, can_close):
        d = _Delim(cc, numdelims, node, can_open, can_close)
        d.previous = self.delimiters
        if d.previous is not None:
            d.previous.next = d
        self.delimiters = d

    def _remove_delimiter(self, delim):
        if delim.previous is not None:
            delim.previous.next = delim.next
        if delim.next is None:
            self.delimiters = delim.previous  # top of stack
        else:
            delim.next.previous = delim.previous

    def _remove_delimiters_between(self, bottom, top):
        if bottom.next is not top:
            bottom.next = top
            top.previous = bottom

    # -- process emphasis ------------------------------------------------
    def process_emphasis(self, stack_bottom):
        closer = self.delimiters
        while closer is not None and closer.previous is not stack_bottom:
            closer = closer.previous
        while closer is not None:
            closercc = closer.cc
            if not closer.can_close:
                closer = closer.next
                continue
            # look back for the first matching opener
            opener = closer.previous
            opener_found = False
            while opener is not None and opener is not stack_bottom:
                odd_match = (
                    (closer.can_open or opener.can_close) and
                    closer.origdelims % 3 != 0 and
                    (opener.origdelims + closer.origdelims) % 3 == 0
                )
                if opener.cc == closercc and opener.can_open and not odd_match:
                    opener_found = True
                    break
                opener = opener.previous
            old_closer = closer
            if closercc in ("*", "_"):
                if not opener_found:
                    closer = closer.next
                else:
                    use_delims = 2 if (
                        closer.numdelims >= 2 and opener.numdelims >= 2) else 1
                    opener_inl = opener.node
                    closer_inl = closer.node
                    opener.numdelims -= use_delims
                    closer.numdelims -= use_delims
                    opener_inl.literal = opener_inl.literal[:-use_delims]
                    closer_inl.literal = closer_inl.literal[:-use_delims]
                    emph = Node("strong" if use_delims == 2 else "emph")
                    tmp = opener_inl._next
                    while tmp is not None and tmp is not closer_inl:
                        nxt = tmp._next
                        tmp.unlink()
                        emph.append_child(tmp)
                        tmp = nxt
                    opener_inl.insert_after(emph)
                    self._remove_delimiters_between(opener, closer)
                    if opener.numdelims == 0:
                        opener_inl.unlink()
                        self._remove_delimiter(opener)
                    if closer.numdelims == 0:
                        closer_inl.unlink()
                        tempstack = closer.next
                        self._remove_delimiter(closer)
                        closer = tempstack
            if not opener_found:
                # SPEC simplification: no openers_bottom optimization.
                # Still drop a delimiter that can't itself be an opener once
                # we've seen there is no matching opener for it.
                if not old_closer.can_open:
                    self._remove_delimiter(old_closer)
        while self.delimiters is not None and self.delimiters is not stack_bottom:
            self._remove_delimiter(self.delimiters)

    # -- delimiter scanning (port of scanDelims) -------------------------
    def scan_delims(self, cc):
        startpos = self.pos
        numdelims = 0
        while self.peek() == cc:
            numdelims += 1
            self.pos += 1
        if numdelims == 0:
            return None
        char_before = previous_char(self.subject, startpos)
        char_after = self.peek()
        if char_after is None:
            char_after = "\n"
        after_ws = _is_ws(char_after)
        after_p = _is_punct(char_after)
        before_ws = _is_ws(char_before)
        before_p = _is_punct(char_before)
        left_flanking = (not after_ws) and ((not after_p) or before_ws or before_p)
        right_flanking = (not before_ws) and ((not before_p) or after_ws or after_p)
        if cc == "_":
            can_open = left_flanking and (not right_flanking or before_p)
            can_close = right_flanking and (not left_flanking or after_p)
        else:
            can_open = left_flanking
            can_close = right_flanking
        self.pos = startpos
        return numdelims, can_open, can_close

    # -- individual handlers ---------------------------------------------
    def handle_delim(self, cc):
        res = self.scan_delims(cc)
        if res is None:
            return False
        numdelims, can_open, can_close = res
        startpos = self.pos
        self.pos += numdelims
        node = self._text(self.subject[startpos:self.pos])
        self._append(node)
        if can_open or can_close:
            self._push_delimiter(cc, numdelims, node, can_open, can_close)
        return True

    def parse_backticks(self):
        ticks = self.match(_RE_TICKS_HERE)
        if ticks is None:
            return False
        after_open = self.pos
        while True:
            m = _RE_TICKS.search(self.subject[self.pos:])
            if m is None:
                break
            if m.group(0) == ticks:
                self.pos += m.end()
                node = Node("code")
                content = self.subject[after_open:self.pos - len(ticks)].replace("\n", " ")
                if (len(content) > 0 and
                        re.search(r"[^ ]", content) is not None and
                        content[0] == " " and content[-1] == " "):
                    node.literal = content[1:-1]
                else:
                    node.literal = content
                self._append(node)
                return True
            # wrong-length backtick run: skip it and keep searching
            self.pos += len(m.group(0))
        # no matching close: literal backticks
        self.pos = after_open
        self._append(self._text(ticks))
        return True

    def parse_backslash(self):
        self.pos += 1
        c = self.peek()
        if c == "\n":
            self.pos += 1
            self._append(Node("linebreak"))
        elif c is not None and c in _ESCAPABLE:
            self._append(self._text(c))
            self.pos += 1
        else:
            self._append(self._text("\\"))
        return True

    def parse_newline(self):
        self.pos += 1
        lastc = self.block._last_child
        if (lastc is not None and lastc.type == "text"
                and lastc.literal and lastc.literal[-1] == " "):
            hardbreak = len(lastc.literal) >= 2 and lastc.literal[-2] == " "
            lastc.literal = lastc.literal.rstrip(" ")
            self._append(Node("linebreak" if hardbreak else "softbreak"))
        else:
            self._append(Node("softbreak"))
        m = _RE_INITIAL_SPACE.match(self.subject[self.pos:])
        if m is not None:
            self.pos += m.end()
        return True

    def parse_string(self):
        m = _RE_MAIN.match(self.subject, self.pos)
        if m is None:
            return False
        self.pos = m.end()
        self._append(self._text(m.group(0)))
        return True

    # -- links (subset: inline links only) ------------------------------
    def spnl(self):
        m = _RE_SPNL.match(self.subject, self.pos)
        if m is not None:
            self.pos = m.end()
        return True

    def parse_link_destination(self):
        res = self.match(_RE_LINK_DEST_BRACES)
        if res is not None:
            return normalize_uri(unescape_string(res[1:-1]))
        if self.peek() == "<":
            return None
        savepos = self.pos
        openparens = 0
        while True:
            c = self.peek()
            if c is None:
                break
            if c == "\\" and (self.at(self.pos + 1) in _ESCAPABLE):
                self.pos += 2
            elif c == "(":
                self.pos += 1
                openparens += 1
            elif c == ")":
                if openparens < 1:
                    break
                self.pos += 1
                openparens -= 1
            elif _is_ws(c):
                break
            else:
                self.pos += 1
        if self.pos == savepos and self.peek() != ")":
            return None
        if openparens != 0:
            return None
        return normalize_uri(unescape_string(self.subject[savepos:self.pos]))

    def parse_link_title(self):
        m = self.match(_RE_LINK_TITLE)
        if m is None:
            return None
        return unescape_string(m[1:-1])

    def add_bracket(self, node, index, image=False):
        if self.brackets is not None:
            self.brackets.bracket_after = True
        br = _Bracket(node, self.brackets, self.delimiters, index)
        br.image = image
        self.brackets = br

    def remove_bracket(self):
        self.brackets = self.brackets.previous

    def parse_open_bracket(self):
        startpos = self.pos
        self.pos += 1
        node = self._text("[")
        self._append(node)
        self.add_bracket(node, startpos)
        return True

    def parse_bang(self):
        # Images (and ``![``) are out of scope: render them as literal text.
        self.pos += 1
        if self.peek() == "[":
            self.pos += 1
            node = self._text("![")
            self._append(node)
            self.add_bracket(node, self.pos - 1, image=True)
        else:
            self._append(self._text("!"))
        return True

    def parse_close_bracket(self):
        self.pos += 1
        startpos = self.pos
        opener = self.brackets
        if opener is None:
            self._append(self._text("]"))
            return True
        if not opener.active:
            self._append(self._text("]"))
            self.remove_bracket()
            return True
        if opener.image:
            # image openers never produce output in this subset -> literal
            self.remove_bracket()
            self._append(self._text("]"))
            return True

        # inline link?  [text](dest "title")
        matched = False
        dest = None
        title = None
        savepos = self.pos
        if self.peek() == "(":
            self.pos += 1
            if (self.spnl() and
                    (dest := self.parse_link_destination()) is not None and
                    self.spnl() and
                    ((_is_ws(self.subject[self.pos - 1]) and
                      (title := self.parse_link_title())) or True) and
                    self.spnl() and
                    self.peek() == ")"):
                self.pos += 1
                matched = True
            else:
                self.pos = savepos

        if matched:
            node = Node("link", destination=dest, title=title or "")
            tmp = opener.node._next
            while tmp is not None:
                nxt = tmp._next
                tmp.unlink()
                node.append_child(tmp)
                tmp = nxt
            self._append(node)
            self.process_emphasis(opener.previous_delimiter)
            self.remove_bracket()
            opener.node.unlink()
            # deactivate all earlier link openers (no links in links)
            opener = self.brackets
            while opener is not None:
                if not opener.image:
                    opener.active = False
                opener = opener.previous
            return True

        # no match: literal
        self.remove_bracket()
        self.pos = startpos
        self._append(self._text("]"))
        return True

    # -- driver -----------------------------------------------------------
    def parse_inline(self):
        c = self.peek()
        if c is None:
            return False
        if c == "\n":
            return self.parse_newline()
        if c == "\\":
            return self.parse_backslash()
        if c == "`":
            return self.parse_backticks()
        if c in ("*", "_"):
            return self.handle_delim(c)
        if c == "[":
            return self.parse_open_bracket()
        if c == "!":
            return self.parse_bang()
        if c == "]":
            return self.parse_close_bracket()
        if c in ('<', '&', '!', "'", '"'):
            # autolinks, raw HTML, entities, images, smart quotes are all out
            # of scope -> plain literal text.
            self.pos += 1
            self._append(self._text(c))
            return True
        return self.parse_string()

    def parse(self, text):
        self.subject = _trim_ascii_ws(text)
        self.pos = 0
        self.delimiters = None
        self.brackets = None
        self.block = Node("_root")
        while self.parse_inline():
            pass
        self.process_emphasis(None)
        return self.block.children_list()


def parse(text):
    """Parse inline ``text`` into a list of inline :class:`Node` objects."""
    return InlineParser().parse(text)