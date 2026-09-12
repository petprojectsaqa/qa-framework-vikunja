"""Runs every reproduction script and prints one line per finding.

Exists because a shell loop over a glob says nothing at all when the glob
matches nothing, which looks identical to everything passing. This finds
the scripts relative to itself, so it works from any directory, and says
plainly when it finds none.

    py scripts/verify_findings.py            # all of them
    py scripts/verify_findings.py VKJ-007    # just one

Standard library only. Exit code 0 means every finding still reproduces.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

FINDINGS = Path(__file__).resolve().parent.parent / "docs" / "findings"
STAND = "http://localhost:3456/health"


def stand_is_up() -> bool:
    try:
        with urllib.request.urlopen(STAND, timeout=5) as response:
            return bool(response.status == 200)
    except (urllib.error.URLError, OSError):
        return False


def main(argv: list[str]) -> int:
    wanted = argv[0].upper() if argv else ""

    if not FINDINGS.is_dir():
        print(f"no findings directory at {FINDINGS}")
        return 2

    scripts = sorted(
        path
        for path in FINDINGS.glob("VKJ-*/reproduce.py")
        if not wanted or wanted in path.parent.name.upper()
    )
    if not scripts:
        where = f" matching {wanted!r}" if wanted else ""
        print(f"no reproduction scripts found{where} under {FINDINGS}")
        return 2

    if not stand_is_up():
        print(f"the stand is not answering at {STAND}")
        print("start it with: docker compose -f docker/docker-compose.yml up -d")
        return 2

    print(f"running {len(scripts)} reproductions against {STAND}\n")
    failed = []
    for script in scripts:
        name = script.parent.name
        started = time.monotonic()
        result = subprocess.run(  # noqa: S603 - fixed paths, no shell
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
        )
        took = time.monotonic() - started
        if result.returncode == 0:
            print(f"  reproduced      {name}  ({took:.1f}s)")
        else:
            failed.append((name, result))
            print(f"  NOT reproduced  {name}  ({took:.1f}s)")

    if failed:
        print(f"\n{len(failed)} did not reproduce. Output of the first:\n")
        name, result = failed[0]
        print(f"--- {name} ---")
        print(result.stdout or "(no output)")
        print(result.stderr or "")
        print(
            "A finding that stops reproducing is worth checking before anything "
            "is sent: the product may have changed, or the script may have."
        )
        return 1

    print("\nEvery finding still reproduces.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
