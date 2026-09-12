"""Webhook sink for the Vikunja QA stand.

Records every request sent to /hook/<name> so the suite can assert on
outgoing webhooks: that one fired at all, what payload it carried and
which headers came with it.

Tests use a unique <name> per test so that recordings stay isolated
while the suite runs in parallel.

Standard library only, on purpose: no build step, no dependency drift.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

_LOCK = threading.Lock()
_RECORDED: dict[str, list[dict]] = defaultdict(list)
_MAX_PER_NAME = 500


def _record(name: str, headers: dict[str, str], body: bytes) -> None:
    try:
        parsed = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None

    entry = {
        "received_at": time.time(),
        "headers": headers,
        "raw_body": body.decode("utf-8", errors="replace"),
        "json": parsed,
    }
    with _LOCK:
        bucket = _RECORDED[name]
        bucket.append(entry)
        if len(bucket) > _MAX_PER_NAME:
            del bucket[:-_MAX_PER_NAME]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # noqa: A003 - silence per-request noise
        pass

    def _send(self, status: int, payload: object) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/_health":
            self._send(200, {"status": "ok"})
            return
        if url.path == "/_recorded":
            name = parse_qs(url.query).get("name", [None])[0]
            with _LOCK:
                if name is None:
                    payload = {k: list(v) for k, v in _RECORDED.items()}
                else:
                    payload = list(_RECORDED.get(name, []))
            self._send(200, payload)
            return
        self._send(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        url = urlparse(self.path)
        if url.path == "/_recorded":
            name = parse_qs(url.query).get("name", [None])[0]
            with _LOCK:
                if name is None:
                    _RECORDED.clear()
                else:
                    _RECORDED.pop(name, None)
            self._send(200, {"cleared": name or "all"})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if not url.path.startswith("/hook/"):
            self._send(404, {"error": "not found"})
            return

        name = url.path[len("/hook/"):]
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        _record(name, dict(self.headers.items()), body)
        self._send(200, {"recorded": name})

    do_PUT = do_POST


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
