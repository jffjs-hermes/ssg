"""Development HTTP server for ssg with hot reload.

``serve()`` composes the existing :func:`ssg.cli.build` pipeline: it renders
``<in>`` to a dedicated output directory (a fresh ``tempfile`` dir by default,
so serving never touches the committed ``dist/`` snapshot) and serves it over
``http.server`` on a chosen host/port.  When reloading is enabled (the
default), a background thread watches ``<in>`` with a stdlib-only mtime/size
poll and re-runs ``build()`` on any change; the server then injects a tiny
client script into every served HTML page that long-polls a lightweight
``/__ssg/reload`` route (also served by the same handler) and reloads the
browser when the build version bumps.  ``--no-reload`` disables the watcher,
the route, and the injection, yielding a plain static server.

No third-party dependencies: everything is ``http.server``, ``threading``,
``os``, ``urllib`` and friends.
"""

import http.server
import mimetypes
import os
import tempfile
import threading
import time
import urllib.parse

from ssg import cli

__all__ = ["serve", "RELOAD_PATH"]

RELOAD_PATH = "/__ssg/reload"
RELOAD_TIMEOUT = 25.0   # max seconds a long-poll holds before returning
WATCH_INTERVAL = 0.4    # watcher poll period in seconds
_IGNORED_DIRS = ("__pycache__", ".git")

_CLIENT_SCRIPT = """<script>
(function () {
  var v = %d;
  function poll() {
    fetch(%r + '?since=' + v, {cache: 'no-store'})
      .then(function (r) { return r.text(); })
      .then(function (nv) {
        nv = parseInt(nv, 10);
        if (nv > v) { window.location.reload(); return; }
        v = nv; setTimeout(poll, 500);
      })
      .catch(function () { setTimeout(poll, 1500); });
  }
  poll();
})();
</script>
"""


# -- build-version signalling ------------------------------------------

class _ReloadState:
    """Holds the current build version and lets long-polls wait for a bump."""

    def __init__(self):
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self.version = 0

    def bump(self):
        with self._cond:
            self.version += 1
            self._cond.notify_all()

    def wait_for_change(self, since, timeout):
        """Block until the version exceeds ``since`` (or ``timeout`` elapses).

        Returns the current version either way.
        """
        with self._cond:
            deadline = time.time() + timeout
            while self.version <= since:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return self.version
                self._cond.wait(remaining)
            return self.version


# -- file watcher ------------------------------------------------------

def _snapshot(in_dir):
    """{absolute_path: (mtime_ns, size)} for every file under ``in_dir``."""
    snap = {}
    for root, dirs, files in os.walk(in_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS]
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            snap[path] = (st.st_mtime_ns, st.st_size)
    return snap


def _watch(in_dir, out_dir, state, stop):
    """Poll ``in_dir``; rebuild into ``out_dir`` and bump ``state`` on change."""
    prev = _snapshot(in_dir)
    while not stop.is_set():
        time.sleep(WATCH_INTERVAL)
        if stop.is_set():
            break
        cur = _snapshot(in_dir)
        if cur != prev:
            cli.build(in_dir, out_dir)
            state.bump()
            prev = cur


# -- HTTP handler ------------------------------------------------------

def _make_handler(out_dir, state, reload_enabled):
    class ServeHandler(http.server.BaseHTTPRequestHandler):
        server_version = "ssg-serve/0.1"

        # -- helpers --------------------------------------------------
        def _resolve_path(self):
            """Map the request path to a safe file under ``out_dir``.

            Returns an absolute filesystem path, or ``None`` when the path is
            outside the served tree (traversal attempt) or missing.
            """
            parsed = urllib.parse.urlparse(self.path)
            rel = urllib.parse.unquote(parsed.path).lstrip("/")
            if not rel:
                rel = "index.html"
            target = os.path.normpath(os.path.join(out_dir, rel))
            root = os.path.normpath(out_dir)
            if target != root and not target.startswith(root + os.sep):
                return None            # traversal
            if os.path.isdir(target):
                target = os.path.join(target, "index.html")
            if not os.path.isfile(target):
                return None
            return target

        def _send_bytes(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        # -- HTTP methods ---------------------------------------------
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if reload_enabled and parsed.path == RELOAD_PATH:
                self._handle_reload(parsed)
                return
            path = self._resolve_path()
            if path is None:
                self._send_bytes(404, b"Not Found\n", "text/plain; charset=utf-8")
                return
            content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
            with open(path, "rb") as f:
                body = f.read()
            if reload_enabled and content_type.startswith("text/html"):
                html = body.decode("utf-8", errors="replace")
                body = html.replace("</body>",
                                    _CLIENT_SCRIPT % (state.version, RELOAD_PATH)
                                    + "</body>").encode("utf-8")
            self._send_bytes(200, body, content_type)

        def _handle_reload(self, parsed):
            qs = urllib.parse.parse_qs(parsed.query)
            try:
                since = int(qs.get("since", ["-1"])[0])
            except ValueError:
                since = -1
            version = state.wait_for_change(since, RELOAD_TIMEOUT)
            self._send_bytes(200, str(version).encode("ascii"),
                             "text/plain; charset=utf-8")

        def log_message(self, format, *args):  # keep the CLI output quiet
            pass

    return ServeHandler


# -- entry point -------------------------------------------------------

def serve(in_dir, host="127.0.0.1", port=8000, out_dir=None, no_reload=False):
    """Serve ``in_dir`` as a built static site; hot-reload unless ``no_reload``.

    Renders ``in_dir`` to ``out_dir`` (a fresh temp dir when ``out_dir`` is
    None) and runs a blocking HTTP server on ``host:port``.  Blocks until the
    server is shut down (e.g. SIGINT).  Returns the listening server so callers
    can read the bound port when they passed ``port=0``.
    """
    in_dir = os.path.abspath(in_dir)
    if not os.path.isdir(in_dir):
        raise SystemExit("error: input directory not found: %s" % in_dir)
    if out_dir is None:
        out_dir = tempfile.mkdtemp(prefix="ssg-serve-")
    out_dir = os.path.abspath(out_dir)

    cli.build(in_dir, out_dir)

    state = _ReloadState()
    stop = threading.Event()
    if not no_reload:
        watcher = threading.Thread(
            target=_watch, args=(in_dir, out_dir, state, stop),
            daemon=True, name="ssg-watch")
        watcher.start()

    handler = _make_handler(out_dir, state, reload_enabled=not no_reload)
    server = http.server.ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address[:2]
    mode = "no-reload" if no_reload else "reload"
    print("Serving on http://%s:%d (reload: %s) -> %s" % (
        actual_host, actual_port, mode, in_dir), flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
    return server