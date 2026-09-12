"""VKJ-001. Reproduction.

The v1 description types Subscription.entity as an integer while the
product returns a string, and the product's own v2 description of the
same field disagrees with the v1 one.

Standard library only, and it imports nothing from the test framework, so
it proves the finding independently of the suite that found it.

    python reproduce.py

Needs the stand from docker/docker-compose.yml to be up.
"""

from __future__ import annotations

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


def call(method: str, url: str, body: object = None, token: str | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {url} failed with {exc.code}: {exc.read().decode()}") from exc


def step(text: str) -> None:
    print(f"\n== {text}")


def main() -> int:
    username = f"vkj001{int(time.time())}"
    email = f"{username}@qa.local"

    step(f"register {username}")
    call(
        "POST",
        f"{API}/api/v1/register",
        {"username": username, "password": PASSWORD, "email": email},
    )

    step("confirm the address with the token from the welcome mail")
    message_id = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        found = call("GET", f"{MAIL}/api/v1/search?query=to%3A{email}")
        messages = found.get("messages") if isinstance(found, dict) else None
        if messages:
            message_id = messages[0]["ID"]
            break
        time.sleep(0.25)
    if message_id is None:
        raise SystemExit("no confirmation mail arrived; is mailpit up?")

    message = call("GET", f"{MAIL}/api/v1/message/{message_id}")
    body = f"{message.get('Text') or ''}{message.get('HTML') or ''}"
    token = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", body).group(1)
    call("POST", f"{API}/api/v1/user/confirm", {"token": token})

    step("log in")
    session = call("POST", f"{API}/api/v1/login", {"username": username, "password": PASSWORD})[
        "token"
    ]

    step("create a project and a task in it")
    project = call("PUT", f"{API}/api/v1/projects", {"title": "VKJ-001"}, session)["id"]
    task = call(
        "PUT", f"{API}/api/v1/projects/{project}/tasks", {"title": "VKJ-001 task"}, session
    )["id"]

    step("what the product actually returns")
    subscription = call("GET", f"{API}/api/v1/tasks/{task}", token=session)["subscription"]
    print(json.dumps(subscription, indent=2))

    step("what the v1 description promises")
    v1 = call("GET", f"{API}/api/v1/docs.json")
    declared_v1 = v1["definitions"]["models.Subscription"]["properties"]["entity"]
    print(json.dumps(declared_v1, indent=2))

    step("what the v2 description promises for the same field")
    v2 = call("GET", f"{API}/api/v2/openapi.json")
    declared_v2 = v2["components"]["schemas"]["Subscription"]["properties"]["entity"]
    print(json.dumps(declared_v2, indent=2))

    actual = subscription["entity"]
    print("\nExpected: the declared type matches the value returned.")
    print(
        f"Actual:   v1 declares {declared_v1.get('type')!r}, "
        f"the product sent {actual!r} ({type(actual).__name__}), "
        f"and v2 declares {declared_v2.get('type')!r}."
    )

    mismatch = declared_v1.get("type") == "integer" and isinstance(actual, str)
    print(
        "\nFinding reproduced." if mismatch else "\nNot reproduced; the product may have changed."
    )
    return 0 if mismatch else 1


if __name__ == "__main__":
    sys.exit(main())
