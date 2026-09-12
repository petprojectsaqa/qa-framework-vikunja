"""VKJ-004. Reproduction.

Operations answer with statuses their own description never mentions.

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

# (method, path, how to provoke it, the status it answers with)
CASES = [
    ("GET", "/user", "no credential at all", None),
]


def call(method: str, url: str, token: str | None = None) -> tuple[int, object]:
    request = urllib.request.Request(url, method=method)
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


def main() -> int:
    spec = json.loads(urllib.request.urlopen(f"{API}/api/v1/docs.json", timeout=30).read())

    reproduced = False
    for method, path, how, _ in CASES:
        status, _body = call(method, f"{API}/api/v1{path}")
        declared = sorted(spec["paths"][path][method.lower()]["responses"])
        print(f"\n== {method} /api/v1{path}  ({how})")
        print(f"  answered with: {status}")
        print(f"  declared:      {', '.join(declared)}")
        if str(status) not in declared:
            print(f"  -> {status} is not declared")
            reproduced = True

    print("\nExpected: every status an operation can answer with appears in its description.")
    print("Actual:   a protected endpoint answers 401 without declaring it.")
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
