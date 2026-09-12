"""The calendar door: the same tasks, reached over CalDAV.

A second entrance to the product's data, with its own verbs (PROPFIND,
REPORT), its own body format (iCalendar rather than JSON) and its own way
in: HTTP Basic, carrying the account password, a CalDAV token, or an API
token that holds the `caldav` permission. Every check built on it asks the
same question, whether the two doors agree about what is behind them.

Like the API clients, this one speaks the protocol and never decides
whether an answer is right.
"""

from __future__ import annotations

from typing import Protocol
from urllib.parse import quote

from vikunja_qa.actors.actor import Actor
from vikunja_qa.auth.strategies import BasicAuth
from vikunja_qa.config import Settings
from vikunja_qa.transport.client import HttpClient
from vikunja_qa.transport.response import ApiResponse

ICALENDAR = "text/calendar; charset=utf-8"

#: What a PROPFIND asks for when all it wants is the listing.
_LISTING = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<D:propfind xmlns:D="DAV:"><D:prop><D:getetag/></D:prop></D:propfind>'
)


class CalendarClient:
    def __init__(self, http: HttpClient) -> None:
        self._http = http

    @classmethod
    def for_account(cls, settings: Settings, username: str, secret: str) -> CalendarClient:
        http = HttpClient(
            settings.dav_url,
            BasicAuth(username, secret),
            timeout=settings.request_timeout,
            attach_traffic=settings.attach_traffic,
        )
        return cls(http)

    @property
    def http(self) -> HttpClient:
        return self._http

    # --- reading ------------------------------------------------------------

    def home(self) -> ApiResponse:
        """GET on the calendar home, the collection holding every project."""
        return self._http.get("/projects/", headers={"Accept": "text/calendar"})

    def calendar(self, project_id: int) -> ApiResponse:
        """One project as a single iCalendar document, every task a VTODO."""
        return self._http.get(f"/projects/{project_id}", headers={"Accept": "text/calendar"})

    def listing(self, project_id: int) -> ApiResponse:
        """PROPFIND with depth 1: the project and one href per task."""
        return self._http.request(
            "PROPFIND",
            f"/projects/{project_id}/",
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            data=_LISTING.encode("utf-8"),
        )

    def todo(self, project_id: int, uid: str) -> ApiResponse:
        return self._http.get(self._todo_path(project_id, uid), headers={"Accept": "text/calendar"})

    # --- writing ------------------------------------------------------------

    def put_todo(self, project_id: int, uid: str, document: str) -> ApiResponse:
        """Create or replace one task, as a calendar client saves it."""
        return self._http.put(
            self._todo_path(project_id, uid),
            headers={"Content-Type": ICALENDAR},
            data=document.encode("utf-8"),
        )

    def delete_todo(self, project_id: int, uid: str) -> ApiResponse:
        return self._http.delete(self._todo_path(project_id, uid))

    @staticmethod
    def _todo_path(project_id: int, uid: str) -> str:
        return f"/projects/{project_id}/{quote(uid, safe='')}.ics"


class CalendarOpener(Protocol):
    """Opens the calendar door as an actor. The secret defaults to the
    account password; a CalDAV token or an API token goes in its place."""

    def __call__(self, actor: Actor, secret: str | None = None) -> CalendarClient: ...
