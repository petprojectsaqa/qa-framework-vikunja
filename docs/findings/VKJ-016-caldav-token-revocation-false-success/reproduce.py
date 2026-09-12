"""VKJ-016. Reproduction.

Revoking a CalDAV token answers "The token was deleted successfully" even
when nothing was revoked: when the token does not exist, and when it
belongs to another account. In the second case the token keeps working.

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
import uuid

API = os.environ.get("VIKUNJA_URL", "http://localhost:3456")
MAIL = os.environ.get("MAILPIT_URL", "http://localhost:18025")
PASSWORD = "VikunjaQA123!"


def call(
    method: str, url: str, body: object = None, token: str | None = None, basic: str | None = None
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if basic:
        request.add_header("Authorization", f"Basic {basic}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            try:
                return response.status, json.loads(raw or b"null")
            except ValueError:
                return response.status, raw.decode("utf-8", "replace")[:80]
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")[:80]


def register(tag: str) -> tuple[str, str]:
    """A fresh, confirmed account. Returns its username and session token."""
    username = f"vkj016{tag}{uuid.uuid4().hex[:6]}"
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
    confirm = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", body).group(1)
    call("POST", f"{API}/api/v1/user/confirm", {"token": confirm})

    _, session = call("POST", f"{API}/api/v1/login", {"username": username, "password": PASSWORD})
    return username, str(session["token"])


def caldav_tokens(session: str) -> list[int]:
    _, listed = call("GET", f"{API}/api/v1/user/settings/token/caldav", token=session)
    return [item["id"] for item in listed] if isinstance(listed, list) else []


def main() -> int:
    alice_name, alice = register("alice")
    _, bob = register("bob")

    print("== revoking a token that does not exist")
    status, body = call("DELETE", f"{API}/api/v1/user/settings/token/caldav/999999999", token=alice)
    print(f"   v1 -> {status} {body}")
    absent_reports_success = 200 <= status < 300

    print("\n== revoking someone else's token")
    _, minted = call("PUT", f"{API}/api/v1/user/settings/token/caldav", token=alice)
    token_id, secret = int(minted["id"]), str(minted["token"])
    print(f"   alice's tokens before: {caldav_tokens(alice)}")

    status, body = call("DELETE", f"{API}/api/v1/user/settings/token/caldav/{token_id}", token=bob)
    print(f"   bob revokes it -> {status} {body}")
    print(f"   alice's tokens after:  {caldav_tokens(alice)}")

    basic = base64.b64encode(f"{alice_name}:{secret}".encode()).decode()
    still, _ = call("GET", f"{API}/dav/projects/{999999999}", basic=basic)
    # 401 means the credential was revoked; anything else means it still authenticates.
    still_works = still != 401
    print(f"   alice's token still opens CalDAV: {still_works} (status {still})")

    foreign_reports_success = 200 <= status < 300

    print("\nExpected: revoking reports success only when a token was revoked.")
    print("Actual:   success is reported for a token that does not exist, and for")
    print("          someone else's token, which goes on working afterwards.")

    reproduced = absent_reports_success and foreign_reports_success and still_works
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
