"""VKJ-013. Reproduction.

After the SMTP server restarts, Vikunja's mail daemon keeps trying to send
on the connection it had before. Each send fails, and the daemon only
re-dials once its queue has been idle for the 30-second timeout. So while
mail keeps flowing at less than one message per 30 seconds, none of it is
delivered: every message is lost for as long as the traffic continues.

This drives the stand's own mail server (mailpit) up and down through
docker compose, so it must run where `docker compose` reaches the stand.
Standard library only, and it imports nothing from the test framework.

    python reproduce.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

API = "http://localhost:3456"
MAIL = "http://localhost:18025"
PASSWORD = "VikunjaQA123!"
COMPOSE = ("docker", "compose", "-f", "docker/docker-compose.yml")

#: The product's mailer.queuetimeout default. Traffic spaced under this keeps
#: the daemon's idle timer from firing, which is the whole point.
QUEUE_TIMEOUT_S = 30
SEND_EVERY_S = 5
RECOVERY_BUDGET_S = 25


def call(method: str, url: str, body: object = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, raw.decode("utf-8", "replace")


def compose(*args: str) -> None:
    subprocess.run([*COMPOSE, *args], check=True, capture_output=True, text=True, timeout=120)


def request_a_mail() -> str:
    """Register a fresh account and return its address. Registration sends a
    confirmation message, which is the mail whose delivery we track."""
    username = f"vkj013{uuid.uuid4().hex[:10]}"
    email = f"{username}@qa.local"
    status, body = call(
        "POST",
        f"{API}/api/v1/register",
        {"username": username, "password": PASSWORD, "email": email},
    )
    if status != 200:
        raise SystemExit(f"registration failed ({status}); is the stand up? {body}")
    return email


def has_arrived(email: str) -> bool:
    _, found = call("GET", f"{MAIL}/api/v1/search?query=to%3A{email}")
    return bool(isinstance(found, dict) and found.get("messages"))


def wait_for_mailpit() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{MAIL}/api/v1/info", timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    raise SystemExit("mailpit did not come back")


def main() -> int:
    sample = request_a_mail()
    time.sleep(3)
    if not has_arrived(sample):
        raise SystemExit("mail is not working before the test even starts; is the stand up?")
    print("baseline mail delivered")

    print("stopping the mail server, requesting one mail during the outage")
    compose("stop", "mailpit")
    request_a_mail()
    compose("start", "mailpit")
    wait_for_mailpit()
    print("mail server is back")

    print(f"sending one mail every {SEND_EVERY_S}s for {RECOVERY_BUDGET_S}s of steady traffic")
    pending = []
    started = time.monotonic()
    while time.monotonic() - started < RECOVERY_BUDGET_S:
        pending.append(request_a_mail())
        time.sleep(SEND_EVERY_S)
    time.sleep(3)
    recovered_under_traffic = any(has_arrived(email) for email in pending)

    print(f"letting the queue fall idle for {QUEUE_TIMEOUT_S + 5}s, then sending one more")
    time.sleep(QUEUE_TIMEOUT_S + 5)
    after_idle = request_a_mail()
    time.sleep(3)
    recovered_after_idle = has_arrived(after_idle)

    print()
    print(f"delivered while traffic continued: {recovered_under_traffic}")
    print(f"delivered after an idle gap:       {recovered_after_idle}")
    print()
    print("Expected: mail resumes once the server is back.")
    print("Actual:   nothing is delivered while traffic continues; only an idle gap recovers it.")

    reproduced = not recovered_under_traffic and recovered_after_idle
    print(
        "\nFinding reproduced." if reproduced else "\nNot reproduced; the product may have changed."
    )
    return 0 if reproduced else 1


if __name__ == "__main__":
    sys.exit(main())
