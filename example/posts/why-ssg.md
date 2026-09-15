# Why a static site generator

A static site generator takes Markdown source and emits plain HTML. No
database, no server-side code, just files.

**Advantages:**

1. Fast to load
2. Easy to version in git
3. Simple to deploy anywhere

**Emphasis and links** work the way you expect: *italics*, **bold**, and
[back to the index](/index.html). Inline code like `python -m ssg build
example dist` renders with a `<code>` tag.

## A nested list

- top level
  - nested item one
  - nested item two
- another top item

ssg handles tight and loose lists, ordered lists that start above one, and
block quotes.