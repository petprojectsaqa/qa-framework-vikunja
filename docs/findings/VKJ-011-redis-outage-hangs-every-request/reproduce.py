"""VKJ-011. Reproduction.

With Redis configured as the key-value store and stopped, an authenticated
request that needs no cache does not fail: it hangs until the client gives
up. One dependency's outage becomes the product's.

This stops and starts the stand's Redis container through docker compose,
so it must run where `docker compose` reaches the stand. The container is
brought back in a finally block, whatever happens.

Standard library only, and it imports nothing from the test framework.

    python reproduce.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("VIKUNJA_URL", "http://localhost:3456")
MAIL = os.environ.get("MAILPIT_URL", "http://localhost:18025")
PASSWORD = "VikunjaQA123!"
COMPOSE = ("docker", "compose", "-f", "docker/docker-compose.yml")

#: Deliberately generous. The question is not whether the request is slow
#: without its cache, but whether it answers at all.
BUDGET_S = 25


def call(
    method: str, url: str, body: object = None, token: str | None = None, timeout: float = 30
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")


def compose(*args: str) -> None:
    subprocess.run([*COMPOSE, *args], check=True, capture_output=True, text=True, timeout=180)


def register() -> str:
    username = f"vkj011{uuid.uuid4().hex[:8]}"
    email = f"{username}@qa.local"
    call(
        "POST",
        f"{API}/api/v1/register",
        {"username": username, "password": PASSWORD, "email": email},
    )

    deadline = time.monotonic() + 30
    message_id = None
    while time.monotonic() < deadline:
        _, found = call("GET", f"{MAIL}/api/v1/search?query=to%3A{email}")
        messages = found.get("messages") if isinstance(found, dict) else None
        if messages:
            message_id = messages[0]["ID"]
            break
        time.sleep(0.25)
    if message_id is None:
        raise SystemExit("no confirmation mail arrived; is mailpit up?")

    _, message = call("GET", f"{MAIL}/api/v1/message/{message_id}")
    body = f"{message.get('Text') or ''}{message.get('HTML') or ''}"
    token = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", body).group(1)
    call("POST", f"{API}/api/v1/user/confirm", {"token": token})

    _, session = call("POST", f"{API}/api/v1/login", {"username": username, "password": PASSWORD})
    return str(session["token"])


def main() -> int:
    token = register()

    started = time.monotonic()
    status, _ = call("GET", f"{API}/api/v1/user", token=token, timeout=BUDGET_S)
    print(f"with Redis up:   GET /user -> {status} in {time.monotonic() - started:.1f}s")

    print("stopping Redis")
    compose("stop", "redis")
    answered: int | None = None
    waited = 0.0
    try:
        started = time.monotonic()
        try:
            answered, _ = call("GET", f"{API}/api/v1/user", token=token, timeout=BUDGET_S)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = type(exc).__name__
        else:
            reason = ""
        waited = time.monotonic() - started
    finally:
        compose("start", "redis")
        print("Redis started again")

    if answered is None:
        print(f"with Redis down: GET /user -> no answer in {waited:.0f}s ({reason})")
    else:
        print(f"with Redis down: GET /user -> {answered} in {waited:.1f}s")

    print("\nExpected: losing a cache degrades the product; the request still answers.")
    print("Actual:   the request never answers, so the caller's connection pool drains.")

    reproduced = answered is None
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
