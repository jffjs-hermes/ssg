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