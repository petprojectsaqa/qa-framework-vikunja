"""VKJ-015. Reproduction.

Two tasks created in the same project at the same moment collide on the
per-project index. One caller wins; every other gets 500 and its task is
not created.

Standard library only, and it imports nothing from the test framework.

    python reproduce.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter

API = os.environ.get("VIKUNJA_URL", "http://localhost:3456")
MAIL = os.environ.get("MAILPIT_URL", "http://localhost:18025")
PASSWORD = "VikunjaQA123!"

#: Two is enough to collide. Six makes the shape obvious.
CALLERS = 6


def call(
    method: str, url: str, body: object = None, token: str | None = None
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")


def register() -> str:
    username = f"vkj015{uuid.uuid4().hex[:8]}"
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


def at_the_same_time(work: list) -> list:
    """Every caller on its own thread, all released by one barrier. Without
    the barrier the calls stagger, and staggered calls do not collide."""
    results: list = [None] * len(work)
    ready = threading.Barrier(len(work))

    def run(index: int, call_it) -> None:  # noqa: ANN001
        ready.wait()
        results[index] = call_it()

    threads = [threading.Thread(target=run, args=(i, w)) for i, w in enumerate(work)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return results


def burst(token: str, project_id: int, label: str) -> Counter:
    answers = at_the_same_time(
        [
            (
                lambda n=n: call(
                    "PUT",
                    f"{API}/api/v1/projects/{project_id}/tasks",
                    {"title": f"racer {n}"},
                    token,
                )
            )
            for n in range(CALLERS)
        ]
    )
    statuses = Counter(status for status, _ in answers)
    print(f"   {label:34s} {dict(sorted(statuses.items()))}")
    return statuses


def main() -> int:
    token = register()

    _, shared = call("PUT", f"{API}/api/v1/projects", {"title": "VKJ-015 shared"}, token)
    print(f"== {CALLERS} tasks created at the same moment")
    together = burst(token, int(shared["id"]), "all in one project")

    print("\n== the control: one project each")
    projects = [
        call("PUT", f"{API}/api/v1/projects", {"title": f"VKJ-015 solo {n}"}, token)[1]
        for n in range(CALLERS)
    ]
    answers = at_the_same_time(
        [
            (
                lambda p=p: call(
                    "PUT", f"{API}/api/v1/projects/{p['id']}/tasks", {"title": "alone"}, token
                )
            )
            for p in projects
        ]
    )
    apart = Counter(status for status, _ in answers)
    print(f"   {'one project each':34s} {dict(sorted(apart.items()))}")

    print("\nExpected: every caller's task is created, whoever else is writing at the time.")
    print("Actual:   in one project, all but one answer 500 and those tasks do not exist.")
    print("          The same callers in separate projects all succeed.")
    print(
        "\nThe server log names the cause: "
        'pq: duplicate key value violates unique constraint "UQE_tasks_tasks_project_index"'
    )

    reproduced = together[500] > 0 and apart.get(500, 0) == 0
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
