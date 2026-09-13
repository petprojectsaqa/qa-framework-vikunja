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
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable


def _address(name: str, default: str) -> str:
    """The same VQA_ variable the suite reads, with the same default.

    The gate has to look at the stand the tests are about to use. It cannot
    import Settings — it runs before the project's dependencies are
    necessarily installed — so it reads the environment directly, and the
    defaults here are the ones in vikunja_qa.config.
    """
    return os.environ.get(f"VQA_{name}", default).rstrip("/")


VIKUNJA = _address("BASE_URL", "http://localhost:3456")
MAILPIT = _address("MAILPIT_URL", "http://localhost:18025")
WEBHOOKS = _address("WEBHOOK_URL", "http://localhost:18080")
PROMETHEUS = _address("PROMETHEUS_URL", "http://localhost:19090")
MINIO = _address("MINIO_URL", "http://localhost:19000")
TESTING_TOKEN = os.environ.get("VQA_TESTING_TOKEN", "qa-stand-testing-token")

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
    except OSError as exc:
        # A service that is still coming up resets the connection rather
        # than refusing it, and that arrives as a bare OSError rather than
        # a URLError. A readiness gate has to treat every flavour of "not
        # yet" the same, or it fails on the very condition it exists to
        # wait out.
        raise StandNotReadyError(f"{method} {url} unreachable: {exc}") from exc

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
        except Exception as exc:  # noqa: BLE001 - anything at all means not ready yet
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(1)
    raise StandNotReadyError(f"{label} never became ready ({last})")


def check_infrastructure() -> None:
    print("infrastructure")
    wait_for("vikunja health", f"{VIKUNJA}/health")
    wait_for("mailpit api", f"{MAILPIT}/api/v1/info")
    wait_for("webhook receiver", f"{WEBHOOKS}/_health")
    wait_for("minio", f"{MINIO}/minio/health/live")
    wait_for("prometheus", f"{PROMETHEUS}/-/ready")


#: The two descriptions, at the exact addresses vikunja_qa.testing.discovery
#: reads. Checked here rather than anywhere else they might also be served:
#: four generated families are built from these two documents at collection
#: time, and a module that cannot read one skips itself. A gate that passed
#: on a neighbouring path would let the whole generated half of the suite
#: disappear quietly, which is the failure this gate exists to prevent.
SPEC_URLS = {"v1": "/api/v1/docs.json", "v2": "/api/v2/openapi.json"}


def check_api_versions() -> None:
    """Prove both API descriptions are readable and describe something."""
    print("api specs")

    status, info = request("GET", f"{VIKUNJA}/api/v1/info")
    if status != 200:
        raise StandNotReadyError(f"/api/v1/info returned {status}")
    version = info.get("version") if isinstance(info, dict) else "?"
    print(f"  ok    product version {version}")

    for label, path in SPEC_URLS.items():
        status, payload = request("GET", f"{VIKUNJA}{path}")
        if status != 200 or not isinstance(payload, dict):
            raise StandNotReadyError(f"the {label} description at {path} returned {status}")
        paths = payload.get("paths")
        if not isinstance(paths, dict) or not paths:
            raise StandNotReadyError(f"the {label} description at {path} describes no paths")
        dialect = payload.get("openapi") or payload.get("swagger") or "?"
        print(f"  ok    {label} description at {path} ({dialect}, {len(paths)} paths)")


def reset_the_stand() -> None:
    """Empty every table, once, before the run begins.

    This is destructive, and it is the only use the suite makes of the
    product's testing API: the one reset that docs/strategy.md, section 2
    allows. Nothing during a run touches it, and the generated sweep
    refuses these routes by name so that walking every published operation
    cannot wipe the stand out from under itself.

    Do not run this script while a suite is running.

    A refusal is reported and not fatal. Isolation in this suite comes from
    ownership rather than from a clean database, so a stand that keeps
    yesterday's rows is still a stand the tests can run against.
    """
    print("reset (destructive: empties every table)")
    status, _ = request("DELETE", f"{VIKUNJA}/api/v1/test/all", raw_auth=TESTING_TOKEN)
    if status in (200, 204):
        print("  ok    every table emptied")
    else:
        print(f"  WARN  the reset endpoint returned {status}; the run continues on existing data")


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
    """Prove Prometheus is actually scraping the product.

    Waited for and then required, not warned about. The side-effect tests
    assert on counters read out of Prometheus, so a target that is down is
    a stand that is not ready, and saying so here names the cause once
    instead of letting it surface as a test failure that blames the
    product.
    """
    print("observability")
    deadline = time.monotonic() + BOOT_DEADLINE
    last = "prometheus has no vikunja target yet"
    while time.monotonic() < deadline:
        status, payload = request("GET", f"{PROMETHEUS}/api/v1/targets")
        if status != 200 or not isinstance(payload, dict):
            last = f"prometheus targets unreadable: {status}"
        else:
            active = payload.get("data", {}).get("activeTargets", [])
            for target in active:
                if target.get("labels", {}).get("job") != "vikunja":
                    continue
                if target.get("health") == "up":
                    print("  ok    prometheus scrapes vikunja")
                    return
                last = f"vikunja target is {target.get('health')}: {target.get('lastError', '')}"
        time.sleep(1)
    raise StandNotReadyError(last)


def with_retries(step: Callable[[], None], attempts: int = 3) -> None:
    """Run a multi-request step again if it trips on a service that is
    still settling.

    The infrastructure waits above poll on their own; this one does not,
    and a single reset partway through a six-request walk would fail the
    gate over exactly the condition it exists to wait out.
    """
    for attempt in range(1, attempts + 1):
        try:
            step()
        except StandNotReadyError as exc:
            if attempt == attempts:
                raise
            print(f"  ..    still settling ({exc}); attempt {attempt + 1} of {attempts}")
            time.sleep(3)
        else:
            return


def main() -> int:
    print("Vikunja QA stand readiness\n")
    try:
        check_infrastructure()
        check_api_versions()
        reset_the_stand()
        with_retries(check_user_path)
        check_metrics_scrape()
    except StandNotReadyError as exc:
        print(f"\nFAILED: {exc}")
        return 1
    print("\nStand is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
