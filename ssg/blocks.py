"""Block-level parser (phase 1) for the ssg Markdown subset.

Turns Markdown source text into a block AST, implementing the strict
CommonMark 0.31.2 subset described in SPEC.md (block rules +1.1, 1.2, 1.6,
1.7, 1.8 and the block-level parts of 1.9).  This is a faithful Python port
of commonmark.js's ``blocks.js`` (BSD-2; SPEC.md names it as the model),
restricted to the SPEC subset: the html_block, setext heading, thematic
break, and indented-code starts are removed (those constructs are out of
scope and fall through to paragraph text), and reference-link-definition
extraction plus inline parsing are omitted (phase 2).

Block structure is resolved first; the inline content of paragraphs and
headings is kept as raw ``content`` text for the phase-2 inline/HTML tasks.

AST node types:

  document     root
  heading      ATX heading, ``heading_level`` 1-6
  paragraph    ``content`` = raw inline source (soft breaks as \n)
  code_block   fenced code; ``language`` (or None) and ``content`` (literal)
  list         bullet/ordered; ``list_data`` {type,start,tight,delimiter,bulletChar,markerOffset,padding}
  item         child block-list item, owns its own ``list_data``
  block_quote  quoted block
"""

import re
from typing import List, Optional

__all__ = ["parse", "Node"]

# --------------------------------------------------------------------------
# regexes lifted from the js reference (subset only)
# ---------------------------------------------------------------------------

_re_nonspace = re.compile(r"[^ \t\f\v\r\n]")
_re_bullet_list_marker = re.compile(r"^[*+-]")
_re_ordered_list_marker = re.compile(r"^(\d{1,9})([.)])")
_re_atx_heading_marker = re.compile(r"^#{1,6}(?:[ \t]+|$)")
_re_code_fence = re.compile(r"^`{3,}(?!.*`)|^~{3,}")
_re_closing_code_fence = re.compile(r"^(?:`{3,}|~{3,})(?=[ \t]*$)")
_re_maybe_special = re.compile(r"^[#`~*+_=<>0-9-]")
_re_tab_tail = re.compile(r"^[ \t]*$")
_re_trailing_hashes = re.compile(r"[ \t]+#+[ \t]*$")
_re_leading_hashes = re.compile(r"^[ \t]*#+[ \t]*$")


def _is_blank(s: str) -> bool:
    return _re_nonspace.search(s) is None


class Node:
    """A generic block-AST node."""

    __slots__ = (
        "type", "children", "_parent", "_open", "_string_content",
        "content", "language", "info", "list_data", "level",
        "_start_line", "_end_line", "_next", "_prev",
        "_fenced", "_fence_char", "_fence_length", "_fence_offset",
    )

    def __init__(self, type_: str):
        self.type = type_
        self.children: List["Node"] = []
        self._parent: Optional["Node"] = None
        self._open = True
        self._string_content: List[str] = []
        self.content: Optional[str] = None
        self.language: Optional[str] = None
        self.info: Optional[str] = None
        self.list_data: Optional[dict] = None
        self.level: Optional[int] = None
        self._start_line = 0
        self._end_line = 0
        self._next: Optional["Node"] = None
        self._prev: Optional["Node"] = None
        self._fenced = False
        self._fence_char: Optional[str] = None
        self._fence_length = 0
        self._fence_offset = 0

    # -- tree helpers -----------------------------------------------------
    def append_child(self, child: "Node") -> "Node":
        child._parent = self
        if self.children:
            self.children[-1]._next = child
            child._prev = self.children[-1]
        self.children.append(child)
        return child

    def unlink(self):
        if self._parent is not None:
            self._parent.children.remove(self)
            self._parent = None
        if self._prev is not None:
            self._prev._next = self._next
        if self._next is not None:
            self._next._prev = self._prev
        self._prev = None
        self._next = None

    def insert_after(self, sibling: "Node"):
        idx = sibling._parent.children.index(sibling)
        sibling._parent.children.insert(idx + 1, self)
        self._parent = sibling._parent
        self._prev = sibling
        self._next = sibling._next
        if sibling._next:
            sibling._next._prev = self
        sibling._next = self

    def is_container(self) -> bool:
        return self.type in ("document", "list", "item", "block_quote")

    def walk(self):
        stack = [self]
        while stack:
            node = stack.pop()
            yield node
            for child in reversed(node.children):
                stack.append(child)

    def _dump(self, indent=0):  # pragma: no cover - debug
        pad = "  " * indent
        extra = ""
        if self.type == "heading":
            extra = " level=%d" % self.level
        elif self.type == "code_block":
            extra = " lang=%r" % self.language
        elif self.type == "list":
            extra = " %r" % self.list_data
        body = ""
        if self.content is not None:
            body = " %r" % self.content
        line = "%s<%s%s>%s\n" % (pad, self.type, extra, body)
        for c in self.children:
            line += c._dump(indent + 1)
        return line

    def __repr__(self):  # pragma: no cover
        return "<Node %s>" % self.type


class BlockParser:
    """Port of commonmark.js block parsing restricted to the SPEC subset.

    The algorithm keeps a stack of open blocks (`tip` is the deepest).  For
    each line we (a) walk down the chain of open containers matching each
    container's continuation rule against the line prefix, (b) try new
    container/leaf starts at the first non-space position, and (c) append the
    remaining text to the current leaf.  Lazy continuation of paragraphs, list
    padding, and nested containers all fall out of these rules.
    """

    def __init__(self):
        self.doc: Optional[Node] = None
        self.tip: Optional[Node] = None
        self.oldtip: Optional[Node] = None
        self.line_number = 0
        self.last_line_length = 0
        self.offset = 0
        self.column = 0
        self.next_nonspace = 0
        self.next_nonspace_column = 0
        self.indent = 0
        self.indented = False
        self.blank = False
        self.partially_consumed_tab = False
        self.all_closed = True
        self.last_matched_container: Optional[Node] = None
        self.current_line = ""

    # ------------------------------------------------------------ offsets
    def advance_offset(self, count: int, columns: bool):
        current = self.current_line
        n = len(current)
        while count > 0 and self.offset < n:
            c = current[self.offset]
            if c == "\t":
                chars_to_tab = 4 - (self.column % 4)
                if columns:
                    self.partially_consumed_tab = chars_to_tab > count
                    chars_to_advance = min(chars_to_tab, count)
                    self.column += chars_to_advance
                    if not self.partially_consumed_tab:
                        self.offset += 1
                    count -= chars_to_advance
                else:
                    self.partially_consumed_tab = False
                    self.column += chars_to_tab
                    self.offset += 1
                    count -= 1
            else:
                self.partially_consumed_tab = False
                self.offset += 1
                self.column += 1
                count -= 1

    def advance_next_nonspace(self):
        self.offset = self.next_nonspace
        self.column = self.next_nonspace_column
        self.partially_consumed_tab = False

    def find_next_nonspace(self):
        current = self.current_line
        i = self.offset
        cols = self.column
        n = len(current)
        while i < n:
            c = current[i]
            if c == " ":
                i += 1
                cols += 1
            elif c == "\t":
                i += 1
                cols += 4 - (cols % 4)
            else:
                break
        self.blank = i >= n
        self.next_nonspace = i
        self.next_nonspace_column = cols
        self.indent = self.next_nonspace_column - self.column
        self.indented = self.indent >= 4

    def _at(self, pos: int, default=""):
        return self.current_line[pos:pos + 1] if pos < len(self.current_line) else default

    # ------------------------------------------------------------- adders
    def add_line(self):
        if self.partially_consumed_tab:
            self.offset += 1  # skip over the tab
            chars_to_tab = 4 - (self.column % 4)
            self.tip._string_content.append(" " * chars_to_tab)
        self.tip._string_content.append(self.current_line[self.offset:])
        self.tip._string_content.append("\n")

    def add_child(self, tag: str, column_number: int) -> Node:
        while not self._can_contain(self.tip, tag):
            self.finalize(self.tip, self.line_number - 1)
        new_block = Node(tag)
        new_block._start_line = self.line_number
        self.tip.append_child(new_block)
        self.tip = new_block
        return new_block

    @staticmethod
    def _can_contain(block: Node, tag: str) -> bool:
        t = block.type
        if t == "document":
            return tag != "item"
        if t in ("item", "block_quote"):
            return tag != "item"
        if t == "list":
            return tag == "item"
        return False

    def finalize(self, block: Node, line_number: int):
        above = block._parent
        block._open = False
        block._end_line = line_number
        self._block_finalize(block)
        self.tip = above

    def _block_finalize(self, block: Node):
        t = block.type
        if t == "list":
            item = block.children[0] if block.children else None
            tight = True
            while item:
                # check the item itself and its descendant chain for a blank
                # line separating two blocks
                candidates = [item]
                cur = item
                while cur.children:
                    cur = cur.children[0]
                    candidates.append(cur)
                for c in candidates:
                    if c._next and self._ends_with_blank_line(c):
                        tight = False
                        break
                if not tight:
                    break
                item = item._next
            block.list_data["tight"] = tight
            # inherit end line from last child
            if block.children:
                block._end_line = block.children[-1]._end_line

        elif t == "item":
            if block.children:
                block._end_line = block.children[-1]._end_line

        elif t == "code_block":
            content = "".join(block._string_content)
            if block._fenced:
                nl = content.find("\n")
                first_line = content[:nl]
                rest = content[nl + 1:] if nl != -1 else ""
                block.info = first_line.strip()
                stripped = first_line.strip()
                block.language = stripped.split(None, 1)[0] if stripped else None
                block.content = rest
            else:
                # indented code (not reachable in this subset but kept correct)
                lines = content.split("\n")
                while lines and _re_tab_tail.match(lines[-1]):
                    lines.pop()
                block.content = "\n".join(lines) + "\n"

        elif t == "paragraph":
            block.content = "".join(block._string_content)[:-1]  # drop trailing \n

        elif t == "heading":
            block.content = "".join(block._string_content)

    def _ends_with_blank_line(self, block: Node) -> bool:
        return block._next is not None and block._end_line != block._next._start_line - 1

    def close_unmatched_blocks(self):
        if not self.all_closed:
            while self.oldtip is not self.last_matched_container:
                parent = self.oldtip._parent
                self.finalize(self.oldtip, self.line_number - 1)
                self.oldtip = parent
            self.all_closed = True

    # -------------------------------------------------------- block starts
    def _start_block_quote(self, container) -> int:
        if not self.indented and self._at(self.next_nonspace) == ">":
            self.advance_next_nonspace()
            self.advance_offset(1, False)
            if self._at(self.offset) in (" ", "\t"):
                self.advance_offset(1, True)
            self.close_unmatched_blocks()
            self.add_child("block_quote", self.next_nonspace)
            return 1
        return 0

    def _start_heading(self, container) -> int:
        if self.indented:
            return 0
        m = _re_atx_heading_marker.match(self.current_line[self.next_nonspace:])
        if m is None:
            return 0
        self.advance_next_nonspace()
        self.advance_offset(m.end(), False)
        self.close_unmatched_blocks()
        c = self.add_child("heading", self.next_nonspace)
        c.level = len(m.group(0).strip())
        content = self.current_line[self.offset:]
        # first: a line that is *only* hashes -> empty
        content = _re_leading_hashes.sub("", content) if content else content
        # then strip trailing " #..." run preceded by whitespace
        content = _re_trailing_hashes.sub("", content)
        c._string_content = [content]
        self.advance_offset(len(self.current_line) - self.offset, False)
        return 2

    def _start_fence(self, container) -> int:
        if self.indented:
            return 0
        m = _re_code_fence.match(self.current_line[self.next_nonspace:])
        if m is None:
            return 0
        fence_length = len(m.group(0))
        self.close_unmatched_blocks()
        c = self.add_child("code_block", self.next_nonspace)
        c._fenced = True
        c._fence_length = fence_length
        c._fence_char = m.group(0)[0]
        c._fence_offset = self.indent
        self.advance_next_nonspace()
        self.advance_offset(fence_length, False)
        return 2

    def _parse_list_marker(self, container):
        """Parse a list marker at the current non-space position, advancing
        offset/column past it.  Returns a data dict or None."""
        rest = self.current_line[self.next_nonspace:]
        data = {
            "type": None, "tight": True, "bulletChar": None,
            "start": None, "delimiter": None, "padding": None,
            "markerOffset": self.indent,
        }
        if self.indent >= 4:
            return None
        m = _re_bullet_list_marker.match(rest)
        if m:
            data["type"] = "bullet"
            data["bulletChar"] = m.group(0)[0]
            marker_len = m.end()
        else:
            mo = _re_ordered_list_marker.match(rest)
            if mo and (container.type != "paragraph" or mo.group(1) == "1"):
                data["type"] = "ordered"
                data["start"] = int(mo.group(1))
                data["delimiter"] = mo.group(2)
            else:
                return None
            marker_len = mo.end()

        # make sure we have a space (or end of line) after the marker
        nxt = self._at(self.next_nonspace + marker_len)
        if nxt not in ("", " ", "\t"):
            return None
        # if it interrupts a paragraph, the rest must be non-blank
        if container.type == "paragraph":
            after = self.current_line[self.next_nonspace + marker_len:]
            if _re_nonspace.search(after) is None:
                return None

        # advance and compute padding (1-4 columns)
        self.advance_next_nonspace()
        self.advance_offset(marker_len, True)
        spaces_start_col = self.column
        spaces_start_offset = self.offset
        while True:
            self.advance_offset(1, True)
            nxt = self._at(self.offset)
            if self.column - spaces_start_col >= 5 or nxt not in (" ", "\t"):
                break
        blank_item = self._at(self.offset) == ""
        spaces_after_marker = self.column - spaces_start_col
        if spaces_after_marker >= 5 or spaces_after_marker < 1 or blank_item:
            data["padding"] = marker_len + 1
            self.column = spaces_start_col
            self.offset = spaces_start_offset
            if self._at(self.offset) in (" ", "\t"):
                self.advance_offset(1, True)
        else:
            data["padding"] = marker_len + spaces_after_marker
        return data

    @staticmethod
    def _lists_match(list_data, item_data) -> bool:
        return (
            list_data["type"] == item_data["type"]
            and list_data["delimiter"] == item_data["delimiter"]
            and list_data["bulletChar"] == item_data["bulletChar"]
        )

    def _start_list_item(self, container) -> int:
        data = None
        if (not self.indented or container.type == "list") and \
                (data := self._parse_list_marker(container)) is not None:
            self.close_unmatched_blocks()
            if self.tip.type != "list" or not self._lists_match(
                    container.list_data, data):
                container = self.add_child("list", self.next_nonspace)
                container.list_data = data
            # add / continue an item
            container = self.add_child("item", self.next_nonspace)
            container.list_data = data
            return 1
        return 0

    # -------------------------------------------------------- continuation
    def _continue(self, container) -> int:
        """Return 0 (matched), 1 (no match), or 2 (line fully consumed)."""
        t = container.type
        ln = self.current_line
        if t == "block_quote":
            if not self.indented and self._at(self.next_nonspace) == ">":
                self.advance_next_nonspace()
                self.advance_offset(1, False)
                if self._at(self.offset) in (" ", "\t"):
                    self.advance_offset(1, True)
            else:
                return 1
            return 0
        if t == "item":
            if self.indent >= container.list_data["markerOffset"] + \
                    container.list_data["padding"]:
                self.advance_offset(
                    container.list_data["markerOffset"] +
                    container.list_data["padding"], True)
            elif self.blank and container.children:
                self.advance_next_nonspace()
            else:
                return 1
            return 0
        if t in ("list", "document"):
            return 0
        if t in ("heading",):
            return 1  # heading cannot continue past one line
        if t == "code_block":
            if container._fenced:
                if self.indent <= 3 and \
                        self._at(self.next_nonspace) == container._fence_char:
                    m = _re_closing_code_fence.match(
                        ln[self.next_nonspace:])
                    if m is not None and len(m.group(0)) >= container._fence_length:
                        self.last_line_length = (
                            self.offset + self.indent + len(m.group(0)))
                        self.finalize(container, self.line_number)
                        return 2
                # skip optional spaces of the fence offset
                i = container._fence_offset
                while i > 0 and self._at(self.offset) in (" ", "\t"):
                    self.advance_offset(1, True)
                    i -= 1
            else:
                if self.indent >= 4:
                    self.advance_offset(4, True)
                elif self.blank:
                    self.advance_next_nonspace()
                else:
                    return 1
            return 0
        if t == "paragraph":
            return 1 if self.blank else 0
        return 0

    # -------------------------------------------------------------- loop
    def incorporate_line(self, ln: str):
        container = self.doc
        self.oldtip = self.tip
        self.offset = 0
        self.column = 0
        self.blank = False
        self.partially_consumed_tab = False
        self.line_number += 1
        self.current_line = ln

        # (a) walk the open container chain matching continuation rules
        last_child = container.children[-1] if container.children else None
        while last_child is not None and last_child._open:
            container = last_child
            self.find_next_nonspace()
            res = self._continue(container)
            if res == 1:
                container = container._parent
                break
            if res == 2:
                self.last_line_length = len(ln)
                return
            last_child = container.children[-1] if container.children else None

        self.all_closed = container is self.oldtip
        self.last_matched_container = container

        # (b) try new container / leaf starts
        matched_leaf = container.type == "code_block"
        starts = (
            self._start_block_quote,
            self._start_heading,
            self._start_fence,
            self._start_list_item,
        )
        done = matched_leaf
        res = 0
        while not done:
            self.find_next_nonspace()
            if self.indented or not _re_maybe_special.match(
                    self.current_line[self.next_nonspace:]):
                # nothing special at this position: content begins here
                self.advance_next_nonspace()
                break
            matched_any = False
            for start in starts:
                res = start(container)
                if res == 1:
                    container = self.tip
                    matched_any = True
                    # keep trying container/leaf starts at the new tip
                    break
                if res == 2:
                    container = self.tip
                    matched_leaf = True
                    done = True
                    break
            if res == 2:
                break
            if not matched_any:
                # none of the block starts matched: content begins here
                self.advance_next_nonspace()
                break

        # (c) add remaining text
        if not self.all_closed and not self.blank and self.tip.type == "paragraph":
            self.add_line()                       # lazy paragraph continuation
        else:
            self.close_unmatched_blocks()
            t = container.type
            if t in ("code_block", "paragraph"):
                self.add_line()
            elif self.offset < len(ln) and not self.blank:
                container = self.add_child("paragraph", self.offset)
                self.advance_next_nonspace()
                self.add_line()
        self.last_line_length = len(ln)

    # ------------------------------------------------------------- driver
    def parse(self, input_text: str) -> Node:
        self.doc = Node("document")
        self.tip = self.doc
        self.oldtip = self.doc
        self.line_number = 0
        self.last_line_length = 0
        self.offset = 0
        self.column = 0
        self.last_matched_container = self.doc
        self.current_line = ""

        lines = input_text.split("\n")
        if input_text and input_text[-1] == "\n":
            lines.pop()  # ignore the blank line from a trailing newline
        for line in lines:
            self.incorporate_line(line)
        while self.tip is not None:
            self.finalize(self.tip, self.line_number)
        self.doc._open = False
        return self.doc


def parse(text: str) -> Node:
    """Parse Markdown ``text`` into a block AST (document root node)."""
    return BlockParser().parse(text)