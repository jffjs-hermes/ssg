"""ssg - minimal Markdown to HTML static-site generator.

Parses the strict CommonMark 0.31.2 subset defined by SPEC.md into a block
AST.  Phase 1 (block structure) lives in :mod:`ssg.blocks`; inline parsing
and HTML rendering are separate phases produced by sibling tasks.
"""

__version__ = "0.1.0"