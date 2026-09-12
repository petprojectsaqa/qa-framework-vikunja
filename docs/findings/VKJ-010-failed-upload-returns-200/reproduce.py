"""VKJ-010. Reproduction.

With object storage stopped, uploading an attachment answers 200 OK and
hides the failure in an `errors` array in the body.

This stops and starts the stand's storage container through docker compose,
so it must run where `docker compose` reaches the stand. The container is
brought back in a finally block, whatever happens.

Standard library only, and it imports nothing from the test framework.

    python reproduce.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("VIKUNJA_URL", "http://localhost:3456")
MAIL = os.environ.get("MAILPIT_URL", "http://localhost:18025")
PASSWORD = "VikunjaQA123!"
COMPOSE = ("docker", "compose", "-f", "docker/docker-compose.yml")
BOUNDARY = "----vkj010boundary"


def call(
    method: str, url: str, body: object = None, token: str | None = None
) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")


def compose(*args: str) -> None:
    subprocess.run([*COMPOSE, *args], check=True, capture_output=True, text=True, timeout=180)


def register() -> str:
    username = f"vkj010{uuid.uuid4().hex[:8]}"
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


def upload(task_id: int, token: str) -> tuple[int, str, float]:
    """Attach a small file, returning status, body and how long it took."""
    payload = (
        f"--{BOUNDARY}\r\n"
        'Content-Disposition: form-data; name="files"; filename="during-outage.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "payload\r\n"
        f"--{BOUNDARY}--\r\n"
    ).encode()
    request = urllib.request.Request(
        f"{API}/api/v1/tasks/{task_id}/attachments", data=payload, method="PUT"
    )
    request.add_header("Content-Type", f"multipart/form-data; boundary={BOUNDARY}")
    request.add_header("Authorization", f"Bearer {token}")

    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, response.read().decode(), time.monotonic() - started
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), time.monotonic() - started


def main() -> int:
    token = register()
    _, project = call("PUT", f"{API}/api/v1/projects", {"title": "VKJ-010"}, token)
    _, task = call("PUT", f"{API}/api/v1/projects/{project['id']}/tasks", {"title": "probe"}, token)

    print("stopping the object storage container")
    compose("stop", "minio")
    try:
        status, body, seconds = upload(int(task["id"]), token)
    finally:
        compose("start", "minio")
        print("object storage started again")

    print()
    print(f"   status:  {status}")
    print(f"   waited:  {seconds:.0f}s")
    print(f"   body:    {body[:300]}")

    print("\nExpected: a failed upload answers with an error status, 502 or 503.")
    print("Actual:   200 OK, with the failure only mentioned in the body.")

    reproduced = status == 200 and "error" in body.lower()
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
