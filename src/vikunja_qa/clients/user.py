"""The signed-in account's own settings.

Only what the suite exercises: CalDAV tokens, the credential a calendar
client is meant to hold instead of the account password.
"""

from __future__ import annotations

from vikunja_qa.clients.base import DomainClient
from vikunja_qa.transport.response import ApiResponse


class UserClient(DomainClient):
    def create_caldav_token(self) -> ApiResponse:
        """Mint a CalDAV token. Its secret appears in this answer only."""
        return self._put("/user/settings/token/caldav")

    def caldav_tokens(self) -> ApiResponse:
        return self._get("/user/settings/token/caldav")

    def delete_caldav_token(self, token_id: int) -> ApiResponse:
        return self._delete(f"/user/settings/token/caldav/{token_id}")
