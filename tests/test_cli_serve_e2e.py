"""End-to-end tests for ``python -m ssg serve`` (dev server + hot reload).

Runs the real CLI as a subprocess against a *copied* copy of the checked-in
``example/`` site (the copy is the fixture that gets mutated, so the shipped
source is never touched).  Each test binds to an ephemeral port (``--port 0``)
and reads the actual assigned port back from the first line of the server's
stdout.

Exercises the acceptance criteria: the server serves every rendered page plus
copied assets; editing a ``.md`` triggers a rebuild and served HTML reflects
the change without restarting the server; static-asset changes also re-serve;
``--no-reload`` runs a plain static server with no watcher and no injected
reload client.
"""

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example")
HOST = "127.0.0.1"
RELOAD_PATH = "/__ssg/reload"

_SERVE_LINE = re.compile(r"http://([\w.:\-]+):(\d+)")


def _env():
    env = dict(os.environ)
    # prepend the repo root so `ssg` resolves to this worktree regardless of cwd
    env["PYTHONPATH"] = ROOT + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _start_serve(site, extra=()):
    """Start ``python -m ssg serve <site> --port 0 [extra...]`` as a subprocess.

    Returns ``(proc, port)`` where ``port`` is the port the server bound to.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "ssg", "serve", site, "--host", HOST,
         "--port", "0", *extra],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_env(),
    )
    try:
        line = proc.stdout.readline()
    except Exception:
        proc.kill()
        proc.wait()
        raise
    m = _SERVE_LINE.search(line)
    if not m:
        proc.kill()
        err = proc.stderr.read() if proc.stderr else ""
        raise AssertionError(
            "serve did not report a listening address; line=%r stderr=%r"
            % (line, err))
    return proc, int(m.group(2))


def _fetch(port, path, timeout=10):
    with urllib.request.urlopen("http://%s:%d%s" % (HOST, port, path),
                                timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8")


def _fetch_status(port, path, timeout=5):
    try:
        code, _ = _fetch(port, path, timeout=timeout)
        return code
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def _wait_up(port, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            code, _ = _fetch(port, "/", timeout=1)
            if code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _wait_for(port, path, needle, timeout=25):
    """Poll ``path`` until its served body contains ``needle`` (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            _, body = _fetch(port, path, timeout=3)
            if needle in body:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def _stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def site(tmp_path):
    """A mutable copy of ``example/`` to serve (source is never edited)."""
    target = tmp_path / "site"
    shutil.copytree(EXAMPLE, target)
    return str(target)


def test_serve_serves_rendered_site_and_assets(site):
    proc, port = _start_serve(site)
    try:
        assert _wait_up(port)
        # rendered pages: index and a post
        code, html = _fetch(port, "/")
        assert code == 200
        assert html.startswith("<!DOCTYPE html>")
        assert "<h1>ssg example site</h1>" in html
        code, post = _fetch(port, "/posts/why-ssg.html")
        assert code == 200
        assert "<h1>" in post and "</html>" in post
        # copied assets are served verbatim
        code, css = _fetch(port, "/static/style.css")
        assert code == 200
        assert "body" in css and "font-family" in css
        code, txt = _fetch(port, "/README.txt")
        assert code == 200
        assert "plain-text asset" in txt
        # the hot-reload client is injected into served HTML
        assert "__ssg" in html and "location.reload" in html
    finally:
        _stop(proc)


def test_reload_endpoint_exists(site):
    proc, port = _start_serve(site)
    try:
        assert _wait_up(port)
        # ?since=-1 resolves immediately to the current build version
        code, body = _fetch(port, RELOAD_PATH + "?since=-1", timeout=5)
        assert code == 200
        assert body.strip().isdigit()
    finally:
        _stop(proc)


def test_serve_hot_reloads_markdown_change(site):
    """Editing a .md rebuilds; served HTML reflects it without a restart."""
    proc, port = _start_serve(site)
    try:
        assert _wait_up(port)
        md = os.path.join(site, "welcome.md")
        with open(md, "a", encoding="utf-8") as f:
            f.write("\n\n## Hot Reload Marker\n\nFresh content after rebuild.\n")
        # wait for the served page to reflect the change
        assert _wait_for(port, "/welcome.html", "Hot Reload Marker"), \
            "served HTML never reflected the .md edit"
        _, body = _fetch(port, "/welcome.html")
        assert "Fresh content after rebuild." in body
    finally:
        _stop(proc)


def test_serve_reloads_static_asset_change(site):
    """Editing a static asset re-serves the new bytes."""
    proc, port = _start_serve(site)
    try:
        assert _wait_up(port)
        css = os.path.join(site, "static", "style.css")
        with open(css, "a", encoding="utf-8") as f:
            f.write("\n/* asset-change-marker */\n")
        assert _wait_for(port, "/static/style.css", "asset-change-marker"), \
            "served asset never reflected the edit"
    finally:
        _stop(proc)


def test_serve_no_reload_runs_plain_static_server(site):
    """--no-reload: static serving only, no watcher, no injected client."""
    proc, port = _start_serve(site, extra=("--no-reload",))
    try:
        assert _wait_up(port)
        # serves content
        _, html = _fetch(port, "/")
        assert "<h1>ssg example site</h1>" in html
        # no injected reload client
        assert "location.reload" not in html
        assert "__ssg" not in html
        # reload endpoint is not exposed
        assert _fetch_status(port, RELOAD_PATH) == 404
        # editing a .md does NOT change the served page (no watcher)
        md = os.path.join(site, "welcome.md")
        with open(md, "a", encoding="utf-8") as f:
            f.write("\n\n## Should Not Appear\n")
        time.sleep(2.5)
        _, body = _fetch(port, "/welcome.html")
        assert "Should Not Appear" not in body
    finally:
        _stop(proc)