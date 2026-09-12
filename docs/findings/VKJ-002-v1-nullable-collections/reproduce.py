"""VKJ-002. Reproduction.

The v1 description declares collection fields non-nullable; the product
returns null for empty ones. The v2 description of the same fields
declares them nullable, which settles which side is wrong.

Standard library only, and it imports nothing from the test framework.

    python reproduce.py
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
FIELDS = ["labels", "assignees", "attachments", "reminders"]


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


def register() -> str:
    username = f"vkj002{int(time.time())}"
    email = f"{username}@qa.local"
    call(
        "POST",
        f"{API}/api/v1/register",
        {"username": username, "password": PASSWORD, "email": email},
    )

    deadline = time.monotonic() + 30
    message_id = None
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

    return str(
        call("POST", f"{API}/api/v1/login", {"username": username, "password": PASSWORD})["token"]
    )


def main() -> int:
    session = register()
    project = call("PUT", f"{API}/api/v1/projects", {"title": "VKJ-002"}, session)["id"]
    task_id = call(
        "PUT",
        f"{API}/api/v1/projects/{project}/tasks",
        {"title": "a task with nothing attached to it"},
        session,
    )["id"]
    task = call("GET", f"{API}/api/v1/tasks/{task_id}", token=session)

    v1 = call("GET", f"{API}/api/v1/docs.json")["definitions"]["models.Task"]["properties"]
    v2 = call("GET", f"{API}/api/v2/openapi.json")["components"]["schemas"]["Task"]["properties"]

    print(f"{'field':16s} {'returned':12s} {'v1 declares':16s} v2 declares")
    print("-" * 66)
    reproduced = False
    for field in FIELDS:
        value = task.get(field)
        declared_v1 = json.dumps(v1.get(field, {}).get("type"))
        declared_v2 = json.dumps(v2.get(field, {}).get("type"))
        print(f"{field:16s} {json.dumps(value):12s} {declared_v1:16s} {declared_v2}")
        if value is None and v1.get(field, {}).get("type") == "array":
            reproduced = True

    print("\nExpected: an empty collection is either [] or declared nullable.")
    print("Actual:   the product sends null, v1 declares a plain array, and")
    print("          v2 declares the same field as nullable.")
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
