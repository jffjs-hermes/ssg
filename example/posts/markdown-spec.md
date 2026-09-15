# Markdown the spec way

ssg implements a strict subset of CommonMark 0.31.2. Here are the constructs
it supports, straight from the spec.

## Headings

Levels 1 through 6 use `#` through `######`.

### Level three heading

## Emphasis and strong

- `*single asterisks*` becomes *emphasis*
- `_underscores_` also become *emphasis*
- `**double asterisks**` become **strong**
- `***triple***` becomes ***strong emphasis***

## Code

Inline code is written with backticks: `a < b & c` is escaped properly.

Fenced blocks carry a language class:

```python
def greet(name):
    return f"hello, {name}"
```

## Ordered lists

3. Third item (the start number is preserved)
4. Fourth item

## Block quotes

> Everything inside here is quoted.
>
> A second quoted paragraph.
