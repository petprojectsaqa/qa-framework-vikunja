"""Attachments go to the report only while a test is running.

The rule exists because Allure raises for an attachment with no test to
hold it, and the generated token scope family reads the product while
pytest is still collecting. See `vikunja_qa.reporting`.
"""

from __future__ import annotations

from typing import Any

import pytest

from vikunja_qa import reporting


@pytest.fixture
def attached(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        reporting.allure, "attach", lambda body, **kwargs: calls.append({"body": body, **kwargs})
    )
    return calls


def test_nothing_is_attached_when_no_test_is_running(
    monkeypatch: pytest.MonkeyPatch, attached: list[dict[str, Any]]
) -> None:
    """What collection looks like: pytest has not set its marker yet."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    reporting.attach("GET /routes -> 200", name="traffic")

    assert attached == []


def test_an_attachment_reaches_allure_while_a_test_runs(attached: list[dict[str, Any]]) -> None:
    """This very test is running, so pytest has set the marker."""
    reporting.attach(b"\x89PNG", name="screen", kind=reporting.AttachmentType.PNG)

    assert attached == [
        {"body": b"\x89PNG", "name": "screen", "attachment_type": reporting.AttachmentType.PNG}
    ]
