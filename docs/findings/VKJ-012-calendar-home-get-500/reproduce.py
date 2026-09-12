"""VKJ-012. Reproduction.

GET and HEAD on the CalDAV calendar home answer 500 with an empty body,
while PROPFIND on the very same collection answers 207.

Standard library only, and it imports nothing from the test framework.

    python reproduce.py
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("VIKUNJA_URL", "http://localhost:3456")
MAIL = os.environ.get("MAILPIT_URL", "http://localhost:18025")
PASSWORD = "VikunjaQA123!"


def call(
    method: str,
    url: str,
    body: object = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def register() -> str:
    """A fresh, confirmed account; returns its username."""
    username = f"vkj012{int(time.time() * 1000) % 10_000_000}"
    email = f"{username}@qa.local"
    call(
        "POST",
        f"{API}/api/v1/register",
        {"username": username, "password": PASSWORD, "email": email},
    )

    deadline = time.monotonic() + 30
    message_id = None
    while time.monotonic() < deadline:
        _, raw = call("GET", f"{MAIL}/api/v1/search?query=to%3A{email}")
        messages = json.loads(raw or b"{}").get("messages")
        if messages:
            message_id = messages[0]["ID"]
            break
        time.sleep(0.2)
    if message_id is None:
        raise SystemExit("no confirmation mail arrived; is mailpit up?")

    _, raw = call("GET", f"{MAIL}/api/v1/message/{message_id}")
    message = json.loads(raw)
    text = f"{message.get('Text') or ''}{message.get('HTML') or ''}"
    token = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", text).group(1)
    call("POST", f"{API}/api/v1/user/confirm", {"token": token})
    return username


def main() -> int:
    username = register()
    basic = base64.b64encode(f"{username}:{PASSWORD}".encode()).decode()
    auth = {"Authorization": f"Basic {basic}"}

    print(f"== CalDAV calendar home, signed in as {username}")
    print(f"   {'request':30s} status  body")
    print("   " + "-" * 50)
    results = {}
    for method, path, extra in (
        ("PROPFIND", "/dav/projects/", {"Depth": "1"}),
        ("GET", "/dav/projects/", {}),
        ("HEAD", "/dav/projects/", {}),
        ("GET", "/dav/projects", {}),
    ):
        status, body = call(method, f"{API}{path}", headers={**auth, **extra})
        results[(method, path)] = status
        print(f"   {method + ' ' + path:30s} {status:<7d} {len(body)} bytes")

    print("\nExpected: a GET on a collection answers with content, 405 or 404, never 500.")
    print("Actual:   PROPFIND works; GET and HEAD on the same collection answer 500.")

    reproduced = (
        results[("PROPFIND", "/dav/projects/")] == 207
        and results[("GET", "/dav/projects/")] == 500
        and results[("HEAD", "/dav/projects/")] == 500
    )
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
