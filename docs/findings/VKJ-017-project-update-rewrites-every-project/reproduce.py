"""VKJ-017. Reproduction.

Updating one project rewrites the `position` and `updated` of every project
on the instance, including projects belonging to other accounts.

Two parts. The first shows one account's rename changing another account's
project, through the API alone — no database access, nothing taken on
trust. The second shows the cost growing in step with the number of
projects the instance holds.

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
import uuid

API = os.environ.get("VIKUNJA_URL", "http://localhost:3456")
MAIL = os.environ.get("MAILPIT_URL", "http://localhost:18025")
PASSWORD = "VikunjaQA123!"

#: Enough for the slope to rise clear of the noise, and quick to build.
FILLER = 500


def call(
    method: str, url: str, body: object = None, token: str | None = None
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")


def register(prefix: str) -> str:
    username = f"{prefix}{uuid.uuid4().hex[:8]}"
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
    found_token = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", body)
    if found_token is None:
        raise SystemExit("the confirmation mail carried no token")
    call("POST", f"{API}/api/v1/user/confirm", {"token": found_token.group(1)})

    _, session = call("POST", f"{API}/api/v1/login", {"username": username, "password": PASSWORD})
    return str(session["token"])


def project(token: str, title: str) -> dict:
    status, made = call("PUT", f"{API}/api/v1/projects", {"title": title}, token)
    if status not in (200, 201) or not isinstance(made, dict):
        raise SystemExit(f"could not create a project: {status} {made}")
    return made


def read(token: str, project_id: int) -> dict:
    status, seen = call("GET", f"{API}/api/v1/projects/{project_id}", token=token)
    if status != 200 or not isinstance(seen, dict):
        raise SystemExit(f"could not read project {project_id}: {status} {seen}")
    return seen


def rename(token: str, project_id: int, title: str) -> float:
    started = time.monotonic()
    status, answered = call("POST", f"{API}/api/v1/projects/{project_id}", {"title": title}, token)
    took = time.monotonic() - started
    if status != 200:
        raise SystemExit(f"could not rename project {project_id}: {status} {answered}")
    return took


def main() -> int:
    alice, bob = register("vkj017a"), register("vkj017b")

    print("== one account renames its own project; another account's is rewritten\n")
    bobs = project(bob, "bob keeps to himself")
    bobs_id = int(bobs["id"])
    before = read(bob, bobs_id)
    print(f"   bob's project, before:  updated={before['updated']}  position={before['position']}")

    alices = project(alice, "alice's project")
    time.sleep(1.2)  # so a changed timestamp cannot be this script's own doing
    rename(alice, int(alices["id"]), "alice renamed her own project")

    after = read(bob, bobs_id)
    print(f"   bob's project, after:   updated={after['updated']}  position={after['position']}")

    rewritten = (before["updated"], before["position"]) != (after["updated"], after["position"])
    print(f"\n   bob did nothing, and his project changed:  {'YES' if rewritten else 'no'}")

    print("\n== and the cost grows with the instance, not with the project\n")
    # Measured as a difference rather than as an absolute, because the
    # absolute depends on how many projects the instance already holds —
    # which a single account cannot see and should not have to.
    quiet = rename(alice, int(alices["id"]), "renamed before")
    print(f"   one rename, as things stand:              {quiet:6.3f}s")
    for n in range(FILLER):
        project(alice, f"filler {n}")
    loaded = rename(alice, int(alices["id"]), "renamed after")
    print(f"   {FILLER} more projects on the instance")
    print(f"   the same rename, unchanged in every way:  {loaded:6.3f}s")
    print(
        f"\n   each further project adds {1000 * (loaded - quiet) / FILLER:.2f} ms to every rename"
    )

    print(
        "\nExpected: renaming a project touches that project.\n"
        "Actual:   it rewrites `position` and `updated` on every project the\n"
        "          instance holds, across every account, and takes time in\n"
        "          proportion to how many there are."
    )
    return 0 if rewritten else 1


if __name__ == "__main__":
    sys.exit(main())
