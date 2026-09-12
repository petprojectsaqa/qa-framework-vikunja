"""VKJ-005. Reproduction.

Refusals carry no usable domain error code, while missing objects do,
which leaves the errors users meet most often untranslatable.

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
ABSENT = 99_999_999


def call(
    method: str, url: str, body: object = None, token: str | None = None
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")


def register(prefix: str) -> str:
    username = f"{prefix}{int(time.time() * 1000) % 10_000_000}"
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
        time.sleep(0.2)
    if message_id is None:
        raise SystemExit("no confirmation mail arrived; is mailpit up?")

    _, message = call("GET", f"{MAIL}/api/v1/message/{message_id}")
    body = f"{message.get('Text') or ''}{message.get('HTML') or ''}"
    token = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", body).group(1)
    call("POST", f"{API}/api/v1/user/confirm", {"token": token})

    _, session = call("POST", f"{API}/api/v1/login", {"username": username, "password": PASSWORD})
    return str(session["token"])


def code_of(body: object) -> object:
    return body.get("code", "<absent>") if isinstance(body, dict) else "<not json>"


def message_of(body: object) -> str:
    if not isinstance(body, dict):
        return ""
    for key in ("message", "detail", "title"):
        if isinstance(body.get(key), str):
            return str(body[key])[:44]
    return ""


def main() -> int:
    owner = register("vkj005a")
    outsider = register("vkj005b")

    _, project = call("PUT", f"{API}/api/v1/projects", {"title": "VKJ-005"}, owner)
    project_id = project["id"]
    _, task = call(
        "PUT", f"{API}/api/v1/projects/{project_id}/tasks", {"title": "VKJ-005 task"}, owner
    )
    task_id = task["id"]

    cases = [
        ("v1 GET a task owned by someone else", "GET", f"{API}/api/v1/tasks/{task_id}"),
        ("v1 GET a task that does not exist", "GET", f"{API}/api/v1/tasks/{ABSENT}"),
        ("v1 GET a project owned by someone else", "GET", f"{API}/api/v1/projects/{project_id}"),
        ("v1 GET a project that does not exist", "GET", f"{API}/api/v1/projects/{ABSENT}"),
        ("v2 GET a task owned by someone else", "GET", f"{API}/api/v2/tasks/{task_id}"),
        ("v2 GET a task that does not exist", "GET", f"{API}/api/v2/tasks/{ABSENT}"),
    ]

    print(f"{'call':42s} {'status':7s} {'code':10s} message")
    print("-" * 104)
    refusals_without_code = 0
    absences_with_code = 0
    for label, method, url in cases:
        status, body = call(method, url, token=outsider)
        code = code_of(body)
        print(f"{label:42s} {status:<7d} {str(code):10s} {message_of(body)}")
        if status == 403 and code in (0, "<absent>"):
            refusals_without_code += 1
        if status == 404 and isinstance(code, int) and code:
            absences_with_code += 1

    print("\nExpected: a refusal carries its own domain code, as a missing object does.")
    print("Actual:   refusals carry 0 on v1 and no field at all on v2.")
    reproduced = refusals_without_code >= 3 and absences_with_code >= 2
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
