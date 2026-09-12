"""VKJ-003. Reproduction.

The v2 description marks most collection fields nullable, but five were
left declared as a plain `object` or `array` while the product returns
`null` in them.

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

#: The field, the schema that describes the response carrying it, and where
#: to read the value from a live instance. `bucket_configuration` is here as
#: the control: it is already declared nullable and must not be reported.
FIELDS = {
    "related_tasks": ("Task", "task"),
    "reactions": ("Task", "task"),
    "extra_settings_links": ("UserGeneralSettings", "user settings"),
    "filter": ("ProjectView", "project view"),
    "bucket_configuration": ("ProjectView", "project view"),
}


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
    username = f"vkj003{int(time.time())}"
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


def declaration(spec: dict, schema_name: str, field: str) -> tuple[str, bool]:
    """How one schema declares one field, and whether that admits null.

    A `$ref` stands for the object schema it points at, which does not admit
    null. A declaration with no type at all constrains nothing, so null is
    allowed and the field is not a finding.
    """
    schemas = spec.get("components", {}).get("schemas") or {}
    described = (schemas.get(schema_name, {}).get("properties") or {}).get(field)
    if described is None:
        return "(not described)", True
    if "$ref" in described:
        return f"$ref {described['$ref'].rsplit('/', 1)[-1]}", False
    if "type" not in described:
        return "(no type)", True
    declared = described["type"]
    rendered = "|".join(declared) if isinstance(declared, list) else str(declared)
    return rendered, "null" in rendered


def live_values(token: str) -> dict[str, object]:
    """The same fields as the product actually sends them."""
    _, project = call("PUT", f"{API}/api/v1/projects", {"title": "VKJ-003"}, token)
    _, task = call(
        "PUT", f"{API}/api/v1/projects/{project['id']}/tasks", {"title": "probe"}, token
    )
    _, views = call("GET", f"{API}/api/v1/projects/{project['id']}/views", token)
    _, settings = call("GET", f"{API}/api/v2/user/settings", token)

    view = views[0] if isinstance(views, list) and views else {}
    seen: dict[str, object] = {}
    for field in ("related_tasks", "reactions"):
        seen[field] = task.get(field)
    seen["extra_settings_links"] = settings.get("extra_settings_links")
    for field in ("filter", "bucket_configuration"):
        seen[field] = view.get(field)
    return seen


def main() -> int:
    token = register()
    _, spec = call("GET", f"{API}/api/v2/openapi.json")
    actual = live_values(token)

    print("== v2 description against what the product sends")
    print(f"   {'field':24s} {'schema':22s} {'declared':22s} {'sent':6s} verdict")
    print("   " + "-" * 84)
    offenders = []
    for field, (schema_name, where) in FIELDS.items():
        says, admits_null = declaration(spec, schema_name, field)
        sends = actual.get(field, "(not returned)")
        rendered = "null" if sends is None else json.dumps(sends)[:6]
        wrong = sends is None and not admits_null
        if wrong:
            offenders.append(field)
        print(
            f"   {field:24s} {schema_name:22s} {says:22s} {rendered:6s} "
            f"{'declares no null' if wrong else 'ok'}   ({where})"
        )

    print("\nExpected: a field the product may send as null is declared nullable.")
    print(f"Actual:   {len(offenders)} of them are not, and arrive as null anyway.")

    # bucket_configuration is the control: already nullable, so a run that
    # reports it means the description changed rather than the finding holding.
    reproduced = bool(offenders) and "bucket_configuration" not in offenders
    print(
        f"\nFinding reproduced ({len(offenders)} fields: {', '.join(offenders)})."
        if reproduced
        else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
