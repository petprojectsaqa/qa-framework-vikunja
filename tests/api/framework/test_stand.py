"""The stand as a whole, before anything is asked of the product.

A framework area. If the instance does not report itself healthy, every
other result is noise, which makes this the cheapest possible smoke check.
"""

from __future__ import annotations

import pytest

from vikunja_qa import stand
from vikunja_qa.config import Settings


@pytest.mark.smoke
def test_the_stand_reports_itself_healthy(settings: Settings) -> None:
    response = stand.health_of(settings.base_url, timeout=10)

    assert response is not None, f"nothing answers at {settings.base_url}"
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
