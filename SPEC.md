# ssg Markdown Specification (Spike)

Defines the exact Markdown feature set ssg parses, and the fixture corpus used to
verify every parser task. All rules below are a **strict subset of CommonMark
0.31.2** (https://spec.commonmark.org/0.31.2/); where a rule is simplified, the
simplification is stated explicitly. Anything not listed here is out of scope and
must be treated as plain text.

Authoritative source: CommonMark Spec 0.31.2, sections 4.2, 4.4, 4.5, 4.8, 4.9,
5.1, 5.2, 5.3, 6.1, 6.2, 6.3, 6.7, 6.8.

## 1. Feature set

### 1.1 ATX headings (CommonMark §4.2)

- 1–6 `#` characters at line start, followed by a space, tab, or end of line.
- Optional closing sequence of `#` characters preceded by one or more spaces/tabs
  is stripped (`## foo ##` → `foo`); trailing `#` not preceded by space are kept.
- Leading spaces before the opening `#` are permitted (up to 3, per CommonMark).
- `#5 bolt` is a paragraph, not a heading (no space after the run of `#`).
- Heading content is parsed as inlines. Empty headings (`#`) are allowed.

### 1.2 Paragraphs (CommonMark §4.8)

- Consecutive non-blank lines that are not recognized as any other block form
  one paragraph; internal newlines are soft line breaks (rendered as a single
  space or newline — ssg renders them as `\n` within the paragraph text).
- A paragraph ends at a blank line, or when interrupted by a heading, fenced
  code block, block quote, or list item.
- Indented code blocks are **out of scope**: a paragraph line indented by 4+
  spaces is still paragraph content. (Deliberate simplification.)

### 1.3 Emphasis and strong emphasis (CommonMark §6.2)

- Delimiters: runs of `*` and `_` (the "delimiter run" model, left/right flanking
  and "both adjacent punctuation" rules per spec §6.2 — but see simplification).
- `*foo*` → emphasis; `**foo**` → strong emphasis; `***foo***` → strong wrapping
  emphasis.
- Same-character nesting: `_foo__bar__baz_`.
- **Intraword rule**: `_` can open/close only when flanking whitespace/punctuation
  per CommonMark (`foo_bar_baz` has no emphasis; `foo*bar*baz` does).
- Simplification: ssg uses a straightforward delimiter-stack parser (spec's
  "process emphasis" algorithm, Appendix) but need not implement the full
  `openers_bottom` modulo-3 optimization for pathological inputs; correctness on
  normal documents is required, linear-time worst case is not.
- Backslash-escaped delimiters (`\*not emphasis\*`) are literal text.

### 1.4 Inline code (CommonMark §6.1)

- Backtick string of length N is closed by a backtick string of the same length.
- Contents are literal: no emphasis, links, or entity expansion inside code spans.
- Leading/trailing space (and only one newlines-collapsed space) is stripped iff
  the content both begins and ends with a space and is not all spaces.
- Code spans take precedence over emphasis and links: `` `a` `` inside a link
  text still forms a code span first.

### 1.5 Links (CommonMark §6.3) — inline links only

- Syntax: `[text](destination "optional title")`.
- Destination: non-empty, either without spaces, or wrapped in `<>`.
- Optional title: `"..."`, `'...'`, or `(...)`, separated from the destination by
  spaces/newlines.
- Link text may contain emphasis, strong, and code spans, but not links
  (a `[` opener deactivates preceding `[` openers — "links within links" rule).
- Reference links (`[foo][bar]`, `[foo][]`, `[foo]`), autolinks, images, and link
  reference definitions are **out of scope**. A stray `[foo]: /url` line is just
  paragraph text.

### 1.6 Fenced code blocks (CommonMark §4.5)

- Opening fence: 3 or more `` ` `` or `~` characters, indented up to 3 spaces.
- Closing fence must be at least as long as the opening fence, same character,
  and may be indented up to 3 spaces; the info string on the opening fence
  (text after the fence chars, e.g. ```python```) is captured as `lang`.
- If an opening `` ` `` fence has an info string, it may not contain backticks.
- Content is literal text, never inline-parsed; entity/escape expansion is off.
- Unclosed fences run to end of document.

### 1.7 Lists (CommonMark §5.2, §5.3)

- Bullet markers: `-`, `+`, `*`. Ordered markers: digits 1–9 followed by `.` or `)`.
- Marker must be followed by at least one space (or a single newline = empty item).
- Content indent = marker width + spaces after it (1–4); continuation lines and
  nested blocks must be indented to that column (lazy continuation allowed for
  paragraphs per spec §5.2).
- Ordered start number is preserved (a list starting `3.` renders from 3).
- Lists are **tight** (items rendered as direct inlines) unless any item contains
  two block-level children separated by a blank line — then loose.
- Changing bullet char or number-marker style starts a **new list**
  (`- a` then `* b` is two lists; `1.` then `2.` is one).
- Indented code blocks inside list items are out of scope (as in §1.2).
- Thematic breaks are out of scope; `- - -` is simply a list of `-` items.

### 1.8 Block quotes (CommonMark §5.1)

- Lines beginning with (up to 3 spaces) `>` optionally followed by one space.
- Lazy continuation: a paragraph line following a block quote line without `>`
  belongs to the quote.
- Block quotes nest; contents are parsed recursively as blocks.
- Block quotes can interrupt paragraphs.

### 1.9 Line breaks (CommonMark §6.7, §6.8)

- Two or more spaces (or a backslash) at end of line → hard break.
- Single newline inside paragraph → soft break.
- Tabs are treated as expanding to the next multiple-of-4 column, per spec §2.2,
  for block-start indentation decisions only.

### 1.10 Explicitly out of scope

Setext headings, thematic breaks, indented code blocks, HTML blocks, raw HTML
inlines, images, autolinks, link reference definitions, entity references,
footnotes, tables, task lists, strikethrough. Unknown constructs are parsed as
plain paragraph text.

## 2. Precedence rules (common to all tasks)

1. Block structure first (phase 1), inlines second (phase 2) — spec Appendix.
2. Code spans win over emphasis and links within a paragraph.
3. Fenced code content is never inline-parsed; block quote markers and list
   markers inside a fenced code block are literal.
4. Links bind tighter than emphasis outside them; emphasis inside link text is
   parsed after the link is recognized (process-emphasis with the `[` opener as
   stack bottom).

## 3. Fixture corpus: tests/spec_fixtures/

Each fixture is a directory `NNN-name/` containing:

- `input.md` — the Markdown source (exact bytes, trailing newline).
- `expected.html` — the expected HTML output.
- `notes.md` — optional; which SPEC.md rule the case exercises.

### Block-level fixtures (owned by the block parser task, used by tests/test_blocks.py)

| Fixture dir | Exercises |
|---|---|
| 001-para-simple | Single paragraph (§1.2) |
| 002-para-multiline | Soft-break joining (§1.2, §1.9) |
| 003-heading-levels | `#`…`######` (§1.1) |
| 004-heading-trailing-hashes | Closing hash sequence stripping (§1.1) |
| 005-heading-no-space | `#5 bolt` is a paragraph (§1.1) |
| 006-heading-interrupts-para | Heading inside paragraph flow (§1.1) |
| 007-fence-backtick | ``` fence with info string (§1.6) |
| 008-fence-tilde | `~~~` fence, no info string (§1.6) |
| 009-fence-unclosed | Fence to EOF (§1.6) |
| 010-fence-not-inline-parsed | `*not emphasis*` inside fence stays literal (§2 rule 3) |
| 011-list-bullet-tight | `-`/`*` tight list (§1.7) |
| 012-list-ordered | `1.` `2.` `3.`, start number kept (§1.7) |
| 013-list-loose | Blank lines between items → loose (§1.7) |
| 014-list-nested | Sublist indented to content column (§1.7) |
| 015-list-para-continuation | Wrapped item lines, lazy continuation (§1.7) |
| 016-list-mixed-markers | `- a` then `* b` = two lists (§1.7) |
| 017-blockquote-simple | Single-level quote (§1.8) |
| 018-blockquote-lazy | Lazy continuation line (§1.8) |
| 019-blockquote-nested | `> > depth 2` (§1.8) |
| 020-blockquote-interrupts-para | Quote after paragraph (§1.8) |
| 021-blank-line-separation | Blocks separated by blank lines (§1.2) |
| 022-mixed-document | Headings + paragraphs + fence + list + quote together |

### Inline fixtures (owned by the inline parser task, used by tests/test_inline.py)

| Fixture dir | Exercises |
|---|---|
| 101-emphasis-star | `*foo*` (§1.3) |
| 102-emphasis-underscore | `_foo_` (§1.3) |
| 103-strong-double | `**foo**` / `__foo__` (§1.3) |
| 104-strong-and-em | `***foo***` (§1.3) |
| 105-emphasis-intraword | `foo_bar_baz` no emphasis; `foo*bar*baz` does (§1.3) |
| 106-emphasis-escaped | `\*literal\*` (§1.3, §1.9) |
| 107-code-span | Simple `` `code` `` (§1.4) |
| 108-code-span-double-backtick | `` ``code`` `` with inner backtick (§1.4) |
| 109-code-span-strip-space | Leading/trailing space stripping rule (§1.4) |
| 110-code-precedence | Code span wins over emphasis (§2 rule 2) |
| 111-link-inline | `[text](/url)` (§1.5) |
| 112-link-title | `[text](/url "title")` (§1.5) |
| 113-link-angle-dest | `[text](</my url>)` (§1.5) |
| 114-link-with-emphasis | Emphasis inside link text (§2 rule 4) |
| 115-nested-links-not-allowed | `[a [b](c) d](e)` — outer is literal (§1.5) |
| 116-hard-break | Trailing double space; trailing backslash (§1.9) |
| 117-combined-inlines | All inline types in one paragraph |

Total: 22 block fixtures + 17 inline fixtures = 39 fixtures.

## 4. Prior art

- CommonMark Spec 0.31.2 — normative reference for every rule above
  (https://spec.commonmark.org/0.31.2/).
- commonmark.js (reference implementation, BSD-2) — the delimiter-stack /
  process-emphasis algorithm in §6.2 and the two-phase parsing strategy in the
  Appendix are modeled directly on its structure.
- cmark (C reference implementation) — same parsing strategy; its
  `blocks.c`/`inlines.c` split maps to ssg's `ssg/blocks.py` / `ssg/inlines.py`.
