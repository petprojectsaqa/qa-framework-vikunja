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


#: How much slower the first request has to be before this is a finding
#: rather than noise. Normal is hundredths of a second, so twenty times is
#: a low bar deliberately: what is being shown is that the product puts no
#: bound of its own on the wait, not that the wait has a particular length.
#: How long it actually lasts is the host's business, and it varies — see
#: "What this depends on" in the report.
DEGRADATION = 20


def probe(token: str, label: str, budget: float) -> tuple[int | None, float]:
    started = time.monotonic()
    try:
        status, _ = call("GET", f"{API}/api/v1/user", token=token, timeout=budget)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        waited = time.monotonic() - started
        print(f"   {label:34} no answer in {waited:.1f}s ({type(exc).__name__})")
        return None, waited
    waited = time.monotonic() - started
    print(f"   {label:34} {status} in {waited:.2f}s")
    return status, waited


def main() -> int:
    token = register()

    print("== GET /api/v1/user, the plainest authenticated call there is\n")
    _, healthy = probe(token, "with Redis up", BUDGET_S)

    compose("stop", "redis")
    try:
        first, blocked = probe(token, "with Redis stopped, first call", BUDGET_S)
        # Asked again, because the answer changes. The product gives up on
        # the store after the first attempts and serves the rest quickly,
        # which is what makes a single measurement of this misleading.
        probe(token, "and again", BUDGET_S)
        probe(token, "and again", BUDGET_S)
    finally:
        compose("start", "redis")
        print("\n   Redis started again")

    print(
        "\nExpected: losing a cache degrades the product, and the product decides\n"
        "          by how much — a call on the common path answers, or fails, within\n"
        "          a bound it sets itself.\n"
        "Actual:   the first calls after the store goes away block for as long as the\n"
        "          host takes to give up on the connection. The product sets no bound;\n"
        "          it inherits whatever the network does. Once it has given up, it\n"
        "          serves the rest normally, which is why one measurement is not enough."
    )

    floor = max(healthy * DEGRADATION, 1.0)
    reproduced = first is None or blocked >= floor
    print(
        f"\nFinding reproduced: the first call took {blocked:.1f}s against {healthy:.2f}s healthy."
        if reproduced
        else f"\nNot reproduced: the first call took {blocked:.1f}s, under the {floor:.1f}s "
        "this looks for. The product may have gained a timeout of its own."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
