"""Does the product's work grow with the request, or with the instance?

VKJ-017 was found by accident: a test began to flake, and chasing it led to
a project update that rewrites every project row in the database. That is a
shape a suite of correctness checks cannot see. Every assertion in this
project passes just as well at ten rows as at ten thousand, and the defect
only shows as a clock.

So this asks the question on purpose. It times each write the product
offers at a series of instance sizes and reports how the cost moves. A cost
that stays flat is what an operation on one row should look like. A cost
that rises with the size of the instance is an operation reaching further
than it was asked to, and that is worth a look whatever the numbers are.

    uv run python scripts/measure_scaling.py            # the default sizes
    uv run python scripts/measure_scaling.py 10 100 400 # sizes of your own

It needs an empty stand, and refuses to run on one that is not: the figures
are ratios between a small instance and a larger one, and starting from
four thousand projects compares four thousand against five. It leaves a few
thousand rows behind, which is the point; `scripts/check_stand.py` empties
them.

Exit code 1 when something grows that nothing accounts for — or when
something on the known list has stopped growing, because a note nobody
removed is worse than none. So this can be run as a check rather than read
as a table.
"""

from __future__ import annotations

import statistics
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from vikunja_qa.actors.actor import Actor
from vikunja_qa.actors.factory import ActorFactory
from vikunja_qa.config import get_settings
from vikunja_qa.db import Database
from vikunja_qa.transport.mailpit import MailpitClient
from vikunja_qa.transport.response import ApiResponse

#: Instance sizes to measure at, in projects. Small enough to build in a
#: couple of minutes, far enough apart for a slope to be a slope.
SIZES = (25, 250, 1000)

#: How many times to time each operation at each size. The median is what
#: gets reported; one sample of anything on a shared machine is a rumour.
SAMPLES = 5

#: How much slower the largest size may be than the smallest before this is
#: called growth. Generous: the interest is in the operations that grow by
#: a factor of ten, not in the ones that drift by a tenth.
TOLERATED_GROWTH = 3.0

#: Operations already known to grow with the instance, and the finding that
#: records why. The same idea as the contract baseline, for the same reason:
#: a check that reports something already written up is a check people stop
#: reading. The list may only shrink, and it says so itself — an entry that
#: stops growing fails, because a note nobody removed is worse than none.
KNOWN_TO_GROW: dict[str, str] = {
    "rename a project": "VKJ-017",
}


@dataclass
class Operation:
    """One write the product offers, and how to perform it."""

    name: str
    perform: Callable[[], ApiResponse]


def timed(perform: Callable[[], ApiResponse]) -> float:
    started = time.monotonic()
    answered = perform()
    took = time.monotonic() - started
    if not answered.ok:
        raise SystemExit(f"the stand refused a measurement call:\n{answered.describe()}")
    return took


def operations(actor: Actor) -> list[Operation]:
    """Every write worth timing, each against something it already owns, so
    that what is measured is the operation and not the setting up."""
    project = actor.api.projects.create("scaling: the project under the clock")
    project_id = int(project["id"])
    task = actor.api.tasks.create(project_id, "scaling: the task under the clock")
    task_id = int(task["id"])
    label = actor.api.labels.create("scaling")
    label_id = int(label["id"])
    team = actor.api.teams.create("scaling")
    team_id = int(team["id"])

    counter = iter(range(1_000_000))
    return [
        Operation(
            "create a project",
            lambda: actor.api.projects.create(f"scaling: made {next(counter)}"),
        ),
        Operation(
            "rename a project",
            lambda: actor.api.projects.update(project_id, title=f"renamed {next(counter)}"),
        ),
        Operation("read a project", lambda: actor.api.projects.get(project_id)),
        Operation("list projects", lambda: actor.api.projects.all()),
        Operation(
            "create a task",
            lambda: actor.api.tasks.create(project_id, f"scaling: made {next(counter)}"),
        ),
        Operation(
            "rename a task",
            lambda: actor.api.tasks.update(task_id, title=f"renamed {next(counter)}"),
        ),
        Operation("read a task", lambda: actor.api.tasks.get(task_id)),
        Operation(
            "rename a label",
            lambda: actor.api.labels.update(label_id, title=f"scaling {next(counter)}"),
        ),
        Operation(
            "rename a team",
            lambda: actor.api.teams.update(team_id, name=f"scaling {next(counter)}"),
        ),
        Operation("read own profile", lambda: actor.v1.get("/user")),
    ]


def grow_to(actor: Actor, projects: int, made: int) -> int:
    """Bring the account up to a number of projects, and say where it got to."""
    while made < projects:
        answered = actor.api.projects.create(f"scaling: filler {made}")
        if not answered.ok:
            raise SystemExit(f"could not build the instance up:\n{answered.describe()}")
        made += 1
    return made


def main(argv: list[str]) -> int:
    sizes = tuple(int(argument) for argument in argv) if argv else SIZES
    settings = get_settings()
    database = Database(settings.db_dsn)

    # Refused, rather than measured, on an instance that is already full.
    # What this reports is a ratio between a small instance and a larger
    # one, and a run starting at four thousand projects compares four
    # thousand against five: every column comes out flat and the conclusion
    # is that nothing grows. That is worse than no measurement at all, and
    # it is what the first run of this script did.
    already = database.count("select count(*) from projects")
    if already > sizes[0]:
        print(
            f"the instance already holds {already} projects and the first size asked for is "
            f"{sizes[0]}.\nEvery column would be measured on top of what is already there, "
            "and nothing would look like it grows.\n"
            "Empty it first:  uv run python scripts/check_stand.py"
        )
        return 2

    mail = MailpitClient(settings.mailpit_url, timeout=settings.mail_timeout)
    actor = ActorFactory(settings, mail, label="scaling").user("owner")

    print(f"timing each operation over {SAMPLES} samples, at {len(sizes)} instance sizes\n")
    measured: dict[str, list[float]] = {}
    held: list[int] = []
    made = 0
    for size in sizes:
        made = grow_to(actor, size, made)
        held.append(database.count("select count(*) from projects"))
        for operation in operations(actor):
            samples = [timed(operation.perform) for _ in range(SAMPLES)]
            measured.setdefault(operation.name, []).append(statistics.median(samples))
        print(f"  measured with {held[-1]} projects on the instance")

    heading = "".join(f"{count:>12}" for count in held)
    print(f"\n{'operation':<22}{heading}{'growth':>10}   known")
    unexpected: list[tuple[str, float]] = []
    settled: list[str] = []
    for name, timings in measured.items():
        cells = "".join(f"{value * 1000:>11.0f}ms" for value in timings)
        growth = timings[-1] / timings[0] if timings[0] else 1.0
        known = KNOWN_TO_GROW.get(name, "")
        print(f"{name:<22}{cells}{growth:>9.1f}x   {known}")
        if growth > TOLERATED_GROWTH and not known:
            unexpected.append((name, growth))
        elif known and growth <= TOLERATED_GROWTH:
            settled.append(name)

    print()
    for name in settled:
        print(
            f"{name} no longer grows. If {KNOWN_TO_GROW[name]} has been fixed, "
            "take it out of KNOWN_TO_GROW; a note nobody removed is worse than none."
        )
    for name, growth in unexpected:
        print(f"{name}: {growth:.1f}x from {held[0]} projects to {held[-1]}, and nothing says why.")

    if unexpected or settled:
        print(
            "\nAn operation on one row that grows with the table is reaching "
            "further than it was asked to."
        )
        return 1

    known_here = ", ".join(f"{name} ({finding})" for name, finding in KNOWN_TO_GROW.items())
    print(
        f"Nothing new grew by more than {TOLERATED_GROWTH:g}x. "
        f"Known and still growing: {known_here}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
