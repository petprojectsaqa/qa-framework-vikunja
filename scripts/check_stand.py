"""Readiness gate for the Vikunja QA stand.

Run this after `docker compose up -d` and before any test run. It proves
every moving part of the stand answers, and it walks one real user path
end to end so that a green result actually means something.

Standard library only: this runs before the project's own dependencies
are necessarily installed.

Exit code 0 means the stand is ready. Anything else means it is not.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
import uuid

VIKUNJA = "http://localhost:3456"
MAILPIT = "http://localhost:18025"
WEBHOOKS = "http://localhost:18080"
MINIO = "http://localhost:19000"
PROMETHEUS = "http://localhost:19090"
TESTING_TOKEN = "qa-stand-testing-token"

TIMEOUT = 10
BOOT_DEADLINE = 120


class StandNotReadyError(Exception):
    pass


def request(
    method: str,
    url: str,
    body: object = None,
    token: str | None = None,
    raw_auth: str | None = None,
) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if raw_auth:
        req.add_header("Authorization", raw_auth)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            payload = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = exc.code
    except urllib.error.URLError as exc:
        raise StandNotReadyError(f"{method} {url} unreachable: {exc.reason}") from exc

    try:
        return status, json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return status, payload.decode("utf-8", errors="replace")


def wait_for(label: str, url: str) -> None:
    deadline = time.monotonic() + BOOT_DEADLINE
    last = ""
    while time.monotonic() < deadline:
        try:
            status, _ = request("GET", url)
            if 200 <= status < 400:
                print(f"  ok    {label}")
                return
            last = f"status {status}"
        except StandNotReadyError as exc:
            last = str(exc)
        time.sleep(1)
    raise StandNotReadyError(f"{label} never became ready ({last})")


def check_infrastructure() -> None:
    print("infrastructure")
    wait_for("vikunja health", f"{VIKUNJA}/health")
    wait_for("mailpit api", f"{MAILPIT}/api/v1/info")
    wait_for("webhook receiver", f"{WEBHOOKS}/_health")
    wait_for("minio", f"{MINIO}/minio/health/live")
    wait_for("prometheus", f"{PROMETHEUS}/-/ready")


def check_api_versions() -> dict[str, str]:
    """Locate both API specs. The v2 spec is generated at runtime, so its
    exact path is discovered rather than assumed."""
    print("api specs")
    found: dict[str, str] = {}

    status, info = request("GET", f"{VIKUNJA}/api/v1/info")
    if status != 200:
        raise StandNotReadyError(f"/api/v1/info returned {status}")
    version = info.get("version") if isinstance(info, dict) else "?"
    print(f"  ok    product version {version}")

    candidates = [
        "/api/v1/swagger/doc.json",
        "/api/v1/docs.json",
        "/api/v2/openapi.json",
        "/api/v2/openapi.yaml",
        "/api/v2/docs.json",
        "/api/v2/schema",
    ]
    for path in candidates:
        try:
            status, payload = request("GET", f"{VIKUNJA}{path}")
        except StandNotReadyError:
            continue
        if status == 200 and isinstance(payload, (dict, str)) and payload:
            marker = ""
            if isinstance(payload, dict):
                if "openapi" in payload:
                    marker = f"openapi {payload['openapi']}"
                elif "swagger" in payload:
                    marker = f"swagger {payload['swagger']}"
                count = len(payload.get("paths", {}))
                marker += f", {count} paths"
            print(f"  ok    spec at {path} ({marker})")
            found[path] = marker
    if not found:
        print("  WARN  no spec endpoint found among the candidates")
    return found


def check_testing_api() -> None:
    print("testing api")
    status, _ = request(
        "DELETE",
        f"{VIKUNJA}/api/v1/test/all",
        raw_auth=TESTING_TOKEN,
    )
    if status in (200, 204):
        print("  ok    truncate endpoint answers")
    else:
        print(f"  WARN  truncate endpoint returned {status}")


def confirm_email(email: str) -> None:
    """Pull the confirmation token out of the registration mail and spend it.

    The stand runs with the mailer enabled, which makes Vikunja park new
    accounts in "email confirmation required" until the token is used.
    Tests walk that real path rather than flipping the status behind the
    product's back: it costs one Mailpit query and keeps the mail
    pipeline continuously proven.
    """
    deadline = time.monotonic() + 30
    message_id = None
    while time.monotonic() < deadline:
        status, found = request("GET", f"{MAILPIT}/api/v1/search?query=to%3A{email}")
        if status == 200 and isinstance(found, dict) and found.get("messages"):
            message_id = found["messages"][0]["ID"]
            break
        time.sleep(0.2)
    if message_id is None:
        raise StandNotReadyError(f"no confirmation mail arrived for {email}")

    status, message = request("GET", f"{MAILPIT}/api/v1/message/{message_id}")
    if status != 200 or not isinstance(message, dict):
        raise StandNotReadyError(f"could not read message {message_id}")

    body = f"{message.get('Text') or ''}\n{message.get('HTML') or ''}"
    match = re.search(r"userEmailConfirm=([A-Za-z0-9_\-]+)", body)
    if not match:
        raise StandNotReadyError("confirmation mail carried no token")

    status, payload = request("POST", f"{VIKUNJA}/api/v1/user/confirm", {"token": match.group(1)})
    if status != 200:
        raise StandNotReadyError(f"confirmation rejected: {status} {payload}")


def check_user_path() -> None:
    """Walk the path every test depends on: register, confirm the address,
    log in, create a project, create a task, read it back."""
    print("user path")
    suffix = uuid.uuid4().hex[:10]
    username = f"stand{suffix}"
    email = f"{username}@qa.local"
    password = "StandCheck123!"

    status, payload = request(
        "POST",
        f"{VIKUNJA}/api/v1/register",
        {"username": username, "password": password, "email": email},
    )
    if status not in (200, 201):
        raise StandNotReadyError(f"registration failed: {status} {payload}")
    print(f"  ok    registered {username}")

    confirm_email(email)
    print("  ok    address confirmed via the registration mail")

    status, payload = request(
        "POST",
        f"{VIKUNJA}/api/v1/login",
        {"username": username, "password": password},
    )
    if status != 200 or not isinstance(payload, dict) or "token" not in payload:
        raise StandNotReadyError(f"login failed: {status} {payload}")
    token = payload["token"]
    print("  ok    logged in, session token issued")

    status, project = request(
        "PUT", f"{VIKUNJA}/api/v1/projects", {"title": f"stand check {suffix}"}, token=token
    )
    if status not in (200, 201) or not isinstance(project, dict):
        raise StandNotReadyError(f"project creation failed: {status} {project}")
    project_id = project["id"]
    print(f"  ok    project {project_id} created")

    status, task = request(
        "PUT",
        f"{VIKUNJA}/api/v1/projects/{project_id}/tasks",
        {"title": "stand check task"},
        token=token,
    )
    if status not in (200, 201) or not isinstance(task, dict):
        raise StandNotReadyError(f"task creation failed: {status} {task}")
    print(f"  ok    task {task['id']} created")

    status, read_back = request("GET", f"{VIKUNJA}/api/v1/tasks/{task['id']}", token=token)
    if (
        status != 200
        or not isinstance(read_back, dict)
        or read_back.get("title") != "stand check task"
    ):
        raise StandNotReadyError(f"task read back failed: {status} {read_back}")
    print("  ok    task read back intact")


def check_metrics_scrape() -> None:
    print("observability")
    status, payload = request("GET", f"{PROMETHEUS}/api/v1/targets")
    if status != 200 or not isinstance(payload, dict):
        raise StandNotReadyError(f"prometheus targets unreadable: {status}")
    active = payload.get("data", {}).get("activeTargets", [])
    vikunja_targets = [t for t in active if t.get("labels", {}).get("job") == "vikunja"]
    if not vikunja_targets:
        print("  WARN  prometheus has no vikunja target yet")
        return
    health = vikunja_targets[0].get("health")
    if health == "up":
        print("  ok    prometheus scrapes vikunja")
    else:
        err = vikunja_targets[0].get("lastError", "")
        print(f"  WARN  vikunja target is {health}: {err}")


def main() -> int:
    print("Vikunja QA stand readiness\n")
    try:
        check_infrastructure()
        check_api_versions()
        check_testing_api()
        check_user_path()
        check_metrics_scrape()
    except StandNotReadyError as exc:
        print(f"\nFAILED: {exc}")
        return 1
    print("\nStand is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
