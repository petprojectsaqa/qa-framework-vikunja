"""VKJ-007. Reproduction.

The v1 description declares label update as PUT; the server answers 405 to
that and accepts POST, which the description does not list.

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
VERBS = ("GET", "PUT", "POST", "PATCH", "DELETE")


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


def register() -> str:
    username = f"vkj007{int(time.time() * 1000) % 10_000_000}"
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


def declared_verbs(spec_url: str, path: str) -> set[str]:
    _, spec = call("GET", spec_url)
    described = spec["paths"].get(path, {})
    return {m.upper() for m in described if m in ("get", "post", "put", "patch", "delete")}


def probe(version: str, session: str) -> None:
    _, created = call(
        "PUT" if version == "v1" else "POST",
        f"{API}/api/{version}/labels",
        {"title": f"VKJ-007 probe {version}"},
        session,
    )
    if not isinstance(created, dict) or "id" not in created:
        print(f"   could not create a label on {version}: {created}")
        return
    label_id = created["id"]

    spec_url = f"{API}/api/v1/docs.json" if version == "v1" else f"{API}/api/v2/openapi.json"
    declared = declared_verbs(spec_url, "/labels/{id}")

    print(f"\n== /api/{version}/labels/{{id}}")
    print(f"   {'verb':8s} {'declared':10s} server")
    print("   " + "-" * 34)
    for verb in VERBS:
        body = {"title": "renamed"} if verb in ("PUT", "POST", "PATCH") else None
        status, _ = call(verb, f"{API}/api/{version}/labels/{label_id}", body, session)
        print(f"   {verb:8s} {('yes' if verb in declared else 'no'):10s} {status}")


def main() -> int:
    session = register()

    probe("v1", session)
    probe("v2", session)

    _, created = call("PUT", f"{API}/api/v1/labels", {"title": "VKJ-007 verdict"}, session)
    label_id = created["id"]
    put_status, _ = call("PUT", f"{API}/api/v1/labels/{label_id}", {"title": "x"}, session)
    post_status, _ = call("POST", f"{API}/api/v1/labels/{label_id}", {"title": "x"}, session)
    declared = declared_verbs(f"{API}/api/v1/docs.json", "/labels/{id}")

    print("\nExpected: the verb the description declares is the verb the server accepts.")
    print("Actual:   v1 declares PUT and rejects it; POST works and is not declared.")

    reproduced = put_status == 405 and post_status == 200 and "PUT" in declared
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
