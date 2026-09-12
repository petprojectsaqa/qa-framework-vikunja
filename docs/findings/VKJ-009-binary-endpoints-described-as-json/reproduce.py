"""VKJ-009. Reproduction.

Two v1 operations serve binary content but declare `produces:
application/json`. The v2 description of the same two operations declares
`image/jpeg` and `application/zip`, which settles which side is wrong, and
one of the v1 entries contradicts itself outright: it claims to produce
JSON while typing its own response as a file.

Reads both descriptions from the running instance. No account needed.

Standard library only, and it imports nothing from the test framework.

    python reproduce.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("VIKUNJA_URL", "http://localhost:3456")

#: (v1 path, v1 verb, v2 path, v2 verb, what it really serves)
OPERATIONS = [
    ("/user/settings/totp/qrcode", "get", "/user/settings/totp/qrcode", "get", "a QR code image"),
    ("/user/export/download", "post", "/user/export/download", "post", "an export archive"),
]


def fetch(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return dict(json.loads(response.read()))
    except (urllib.error.URLError, OSError) as exc:
        raise SystemExit(f"could not read {url}: {exc}. Is the stand up?") from exc


def v1_declaration(spec: dict, path: str, verb: str) -> tuple[str, str]:
    """What v1 says it produces, and how it types the 200 body."""
    operation = (spec.get("paths", {}).get(path) or {}).get(verb) or {}
    produces = ", ".join(operation.get("produces") or []) or "(not stated)"
    schema = ((operation.get("responses") or {}).get("200") or {}).get("schema") or {}
    if "$ref" in schema:
        body = schema["$ref"].rsplit("/", 1)[-1]
    else:
        body = str(schema.get("type", "(no schema)"))
    return produces, body


def v2_content_types(spec: dict, path: str, verb: str) -> str:
    operation = (spec.get("paths", {}).get(path) or {}).get(verb) or {}
    ok = (operation.get("responses") or {}).get("200") or {}
    return ", ".join((ok.get("content") or {}).keys()) or "(not stated)"


def main() -> int:
    v1 = fetch(f"{API}/api/v1/docs.json")
    v2 = fetch(f"{API}/api/v2/openapi.json")

    print("== the same operations, described by the two versions")
    print(f"   {'operation':34s} {'v1 produces':20s} {'v1 body':16s} v2 content type")
    print("   " + "-" * 94)
    offenders = []
    for v1_path, v1_verb, v2_path, v2_verb, serves in OPERATIONS:
        produces, body = v1_declaration(v1, v1_path, v1_verb)
        v2_types = v2_content_types(v2, v2_path, v2_verb)
        name = f"{v1_verb.upper()} {v1_path}"
        print(f"   {name:34s} {produces:20s} {body:16s} {v2_types}")
        if "application/json" in produces and "json" not in v2_types:
            offenders.append((name, serves, v2_types))

    print()
    for name, serves, v2_types in offenders:
        print(f"   {name} serves {serves}; v2 describes it as {v2_types}, v1 as application/json.")

    contradiction = [
        f"{verb.upper()} {path}"
        for path, verb, _, _, _ in OPERATIONS
        if v1_declaration(v1, path, verb) == ("application/json", "file")
    ]
    if contradiction:
        print(
            "\n   v1 also contradicts itself on "
            + ", ".join(contradiction)
            + ': produces "application/json" with a response typed "file".'
        )

    print("\nExpected: an operation serving binary content declares a binary content type.")
    print("Actual:   v1 declares application/json for both; v2 declares the real types.")

    reproduced = len(offenders) == len(OPERATIONS)
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
