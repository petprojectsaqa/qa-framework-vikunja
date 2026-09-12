"""VKJ-008. Reproduction.

The v2 API declares one error format for every operation and then answers
authentication failures in a different one.

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
) -> tuple[int, dict[str, str], object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, dict(response.headers), json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, dict(exc.headers), json.loads(raw)
        except ValueError:
            return exc.code, dict(exc.headers), raw.decode("utf-8", "replace")


def register() -> str:
    username = f"vkj008{int(time.time() * 1000) % 10_000_000}"
    email = f"{username}@qa.local"
    call(
        "POST",
        f"{API}/api/v1/register",
        {"username": username, "password": PASSWORD, "email": email},
    )

    deadline = time.monotonic() + 30
    message_id = None
    while time.monotonic() < deadline:
        _, _, found = call("GET", f"{MAIL}/api/v1/search?query=to%3A{email}")
        messages = found.get("messages") if isinstance(found, dict) else None
        if messages:
            message_id = messages[0]["ID"]
            break
        time.sleep(0.2)
    if message_id is None:
        raise SystemExit("no confirmation mail arrived; is mailpit up?")

    _, _, message = call("GET", f"{MAIL}/api/v1/message/{message_id}")
    body = f"{message.get('Text') or ''}{message.get('HTML') or ''}"
    token = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", body).group(1)
    call("POST", f"{API}/api/v1/user/confirm", {"token": token})

    _, _, session = call(
        "POST", f"{API}/api/v1/login", {"username": username, "password": PASSWORD}
    )
    return str(session["token"])


def main() -> int:
    print("== what the v2 description promises for every operation")
    _, _, spec = call("GET", f"{API}/api/v2/openapi.json")
    declared = spec["paths"]["/projects"]["get"]["responses"]["default"]
    print(json.dumps(declared, indent=2)[:300])

    model = spec["components"]["schemas"]["VikunjaErrorModel"]
    print(f"\n   additionalProperties: {model.get('additionalProperties')}")
    print(f"   properties: {sorted(model.get('properties', {}))}")

    session = register()

    print("\n== a domain error, produced by a handler")
    status, headers, body = call("GET", f"{API}/api/v2/tasks/{ABSENT}", token=session)
    print(f"   status {status}, content-type {headers.get('Content-Type')}")
    print(f"   {json.dumps(body, ensure_ascii=False)[:200]}")

    print("\n== an authentication error, produced by the middleware")
    status_401, headers_401, body_401 = call("GET", f"{API}/api/v2/projects")
    print(f"   status {status_401}, content-type {headers_401.get('Content-Type')}")
    print(f"   {json.dumps(body_401, ensure_ascii=False)[:200]}")

    wrong_type = "problem+json" not in (headers_401.get("Content-Type") or "")
    undeclared_field = isinstance(body_401, dict) and "message" in body_401
    missing_detail = isinstance(body_401, dict) and "detail" not in body_401

    print("\nExpected: every v2 error matches the declared model and content type.")
    print("Actual:   middleware errors use the v1 shape instead.")
    print(f"   wrong content type:        {wrong_type}")
    print(f"   undeclared 'message' field: {undeclared_field}")
    print(f"   declared 'detail' missing:  {missing_detail}")

    reproduced = wrong_type and undeclared_field and missing_detail
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
