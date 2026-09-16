"""End-to-end test: ``python -m ssg build example <out>``.

Runs the real CLI as a subprocess against the checked-in ``example/`` site,
then asserts every Markdown file became an HTML page and every non-Markdown
file was copied through verbatim.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example")

# Every .md in example/ maps to {rel}.html; everything else is copied as-is.
_EXPECTED_PAGES = [
    "index.html",
    "welcome.html",
    "posts/why-ssg.html",
    "posts/markdown-spec.html",
    "posts/code-samples.html",
]
_EXPECTED_ASSETS = [
    "static/style.css",
    "README.txt",
]


def _input_files():
    return [f for _, _, files in os.walk(EXAMPLE) for f in files]


def _relative_input_files():
    out = set()
    for root, _, files in os.walk(EXAMPLE):
        for f in files:
            out.add(os.path.relpath(os.path.join(root, f), EXAMPLE))
    return out


def _expected_output_map():
    """{output_rel_path: input_rel_path} for every source file."""
    return {
        "index.html": "index.md",
        "welcome.html": "welcome.md",
        "posts/why-ssg.html": "posts/why-ssg.md",
        "posts/markdown-spec.html": "posts/markdown-spec.md",
        "posts/code-samples.html": "posts/code-samples.md",
        "static/style.css": "static/style.css",
        "README.txt": "README.txt",
    }


def test_example_site_has_at_least_three_posts():
    md_files = [f for f in _relative_input_files() if f.endswith(".md")]
    assert len(md_files) >= 3


def test_cli_build_produces_all_files(tmp_path):
    """`python -m ssg build example <out>` leaves no missing files."""
    out = tmp_path / "dist"
    env = dict(os.environ)
    # prepend the repo root so `ssg` resolves here regardless of cwd
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-m", "ssg", "build", EXAMPLE, str(out)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr

    mapping = _expected_output_map()
    for out_rel, src_rel in mapping.items():
        src = os.path.join(EXAMPLE, src_rel)
        dst = os.path.join(str(out), out_rel)
        assert os.path.isfile(src), "test fixture missing: %s" % src
        assert os.path.isfile(dst), "build missing output: %s" % out_rel


def test_cli_build_copies_assets_verbatim(tmp_path):
    out = tmp_path / "dist"
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(
        [sys.executable, "-m", "ssg", "build", EXAMPLE, str(out)],
        capture_output=True, check=True, env=env,
    )
    for asset in _EXPECTED_ASSETS:
        src = os.path.join(EXAMPLE, asset)
        dst = os.path.join(str(out), asset)
        assert os.path.isfile(dst)
        with open(src, "rb") as a, open(dst, "rb") as b:
            assert a.read() == b.read(), "asset not copied verbatim: %s" % asset


def test_built_page_is_full_html_document(tmp_path):
    out = tmp_path / "dist"
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(
        [sys.executable, "-m", "ssg", "build", EXAMPLE, str(out)],
        capture_output=True, check=True, env=env,
    )
    with open(out / "index.html", encoding="utf-8") as f:
        html = f.read()
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>" in html and "</title>" in html
    # page title comes from the first heading, flattened to text
    assert "<title>ssg example site</title>" in html
    # body wraps the rendered markdown fragment
    assert "<h1>ssg example site</h1>" in html


def test_cli_build_errors_on_missing_input(tmp_path):
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    missing = tmp_path / "does-not-exist"
    result = subprocess.run(
        [sys.executable, "-m", "ssg", "build", str(missing), str(tmp_path / "out")],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr


def _write_site(tmp_path, body):
    """Write a one-page markdown site and return its input dir path."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.md").write_text(body, encoding="utf-8")
    return str(site)


_HIGHLIGHT_PAGE = (
    "# Hi\n"
    "\n"
    "A python fence:\n"
    "\n"
    "```python\n"
    "def greet(name):\n"
    "    return 'hi ' + name\n"
    "```\n"
)


def test_cli_build_without_highlight_has_no_token_spans(tmp_path):
    """Default build (`--highlight` absent) emits no Pygments token spans."""
    out = tmp_path / "dist"
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(
        [sys.executable, "-m", "ssg", "build",
         _write_site(tmp_path, _HIGHLIGHT_PAGE), str(out)],
        capture_output=True, check=True, env=env,
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    assert '<span class="' not in html
    # fenced body stays a literal (HTML-escaped)
    assert "def greet(name):" in html


def test_cli_build_with_highlight_emits_token_spans(tmp_path):
    """`--highlight` renders recognized fenced code with Pygments spans."""
    out = tmp_path / "dist"
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(
        [sys.executable, "-m", "ssg", "build", "--highlight",
         _write_site(tmp_path, _HIGHLIGHT_PAGE), str(out)],
        capture_output=True, check=True, env=env,
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="language-python"' in html
    assert '<span class="' in html
    # the literal still renders (as a token)
    assert "def" in html


def test_cli_build_with_highlight_falls_back_on_unknown_lang(tmp_path):
    """Unknown fenced language under `--highlight` falls back to the literal."""
    out = tmp_path / "dist"
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    body = "# T\n\n```madeuplang999\nraw <content>&\n```\n"
    subprocess.run(
        [sys.executable, "-m", "ssg", "build", "--highlight",
         _write_site(tmp_path, body), str(out)],
        capture_output=True, check=True, env=env,
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    # escaped literal fallback, no token spans
    assert "<span" not in html
    assert "raw &lt;content&gt;&amp;" in html


def test_cli_build_highlight_flag_matches_default_output_structure(tmp_path):
    """Highlighted page keeps the same full-HTML-document wrapper."""
    out = tmp_path / "dist"
    env = dict(os.environ)
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(
        [sys.executable, "-m", "ssg", "build", "--highlight",
         _write_site(tmp_path, _HIGHLIGHT_PAGE), str(out)],
        capture_output=True, check=True, env=env,
    )
    html = (out / "index.html").read_text(encoding="utf-8")
    assert html.startswith("<!DOCTYPE html>")
    assert "<h1>Hi</h1>" in html
    assert "<pre><code" in html and "</code></pre>" in html