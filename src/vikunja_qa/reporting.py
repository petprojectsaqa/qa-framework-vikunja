"""Attaching evidence to the report from code that does not know where it runs.

Framework code runs in three places: inside a test, where Allure records
what it is given; in scripts, where there is no report at all; and while
pytest is still collecting, where a report is being written but no test
exists yet to hold an attachment. Allure tolerates a step in that last
place and raises `KeyError` for an attachment.

That difference cost the suite a whole test family. The token scope matrix
reads the product during collection, the transport attached its traffic
directly, and so every run that wrote Allure results, which is every CI
run, skipped the family with a one-line `KeyError: None` nobody read. The
coverage matrix summary is what finally showed a P0 check with no tests.

pytest sets `PYTEST_CURRENT_TEST` exactly while a test, or a fixture on its
behalf, is running, which is exactly when there is something to attach to.
Everything in the framework attaches through here.
"""

from __future__ import annotations

import os

import allure
from allure_commons.types import AttachmentType

_RUNNING_TEST = "PYTEST_CURRENT_TEST"


def attach(body: str | bytes, *, name: str, kind: AttachmentType = AttachmentType.TEXT) -> None:
    """Attach to the running test's report entry; do nothing when none is running."""
    if _RUNNING_TEST not in os.environ:
        return
    allure.attach(body, name=name, attachment_type=kind)
