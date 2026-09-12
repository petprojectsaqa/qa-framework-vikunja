"""Teams, labels, link shares and API tokens.

Grouped together because each is a second route to access: a caller can
reach a project through a team, through a public link, or through a
scoped token, and every one of those routes needs its own row in the
access matrix.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from vikunja_qa.clients.base import DomainClient
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.transport.response import ApiResponse


class TeamsClient(DomainClient):
    def create(self, name: str, **fields: Any) -> ApiResponse:
        return self._put("/teams", json={"name": name, **fields})

    def get(self, team_id: int) -> ApiResponse:
        return self._get(f"/teams/{team_id}")

    def all(self) -> ApiResponse:
        return self._get("/teams")

    def update(self, team_id: int, **fields: Any) -> ApiResponse:
        return self._post(f"/teams/{team_id}", json=fields)

    def delete(self, team_id: int) -> ApiResponse:
        return self._delete(f"/teams/{team_id}")

    def add_member(self, team_id: int, username: str, admin: bool = False) -> ApiResponse:
        return self._put(f"/teams/{team_id}/members", json={"username": username, "admin": admin})

    def remove_member(self, team_id: int, username: str) -> ApiResponse:
        return self._delete(f"/teams/{team_id}/members/{username}")


class LabelsClient(DomainClient):
    def create(self, title: str, **fields: Any) -> ApiResponse:
        return self._put("/labels", json={"title": title, **fields})

    def get(self, label_id: int) -> ApiResponse:
        return self._get(f"/labels/{label_id}")

    def all(self) -> ApiResponse:
        return self._get("/labels")

    def update(self, label_id: int, **fields: Any) -> ApiResponse:
        """POST, not PUT.

        The v1 description says PUT and the product answers 405 to it;
        POST is what actually works. See VKJ-007. v2 accepts PUT, so a
        cross-version test has to send different verbs on purpose.
        """
        return self._post(f"/labels/{label_id}", json=fields)

    def delete(self, label_id: int) -> ApiResponse:
        return self._delete(f"/labels/{label_id}")


class SharesClient(DomainClient):
    """Public links to a project.

    A share carries a permission level and may sit behind a password, so
    the matrix walks both axes. Its token is meant to reach exactly one
    project, which is the property GHSA-2pv8-4c52-mf8j broke.
    """

    def create(
        self,
        project_id: int,
        permission: Permission = Permission.READ,
        password: str | None = None,
        name: str = "",
    ) -> ApiResponse:
        body: dict[str, Any] = {"permission": int(permission)}
        if password:
            body["password"] = password
        if name:
            body["name"] = name
        return self._put(f"/projects/{project_id}/shares", json=body)

    def all(self, project_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}/shares")

    def get(self, project_id: int, share_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}/shares/{share_id}")

    def delete(self, project_id: int, share_id: int) -> ApiResponse:
        return self._delete(f"/projects/{project_id}/shares/{share_id}")

    def authenticate(self, share_hash: str, password: str | None = None) -> ApiResponse:
        """Trade the public hash for a token scoped to that one project."""
        body: dict[str, Any] = {"hash": share_hash}
        if password:
            body["password"] = password
        return self._post(f"/shares/{share_hash}/auth", json=body)


class TokensClient(DomainClient):
    """Scoped API tokens.

    The permission map is `{area: [action, ...]}`, and the product
    publishes the full set of valid keys itself, which is what lets the
    scope matrix be generated rather than maintained by hand.
    """

    def create(
        self,
        title: str,
        permissions: dict[str, list[str]],
        expires_in: timedelta = timedelta(days=30),
    ) -> ApiResponse:
        expiry = (datetime.now(UTC) + expires_in).strftime("%Y-%m-%dT%H:%M:%SZ")
        return self._put(
            "/tokens",
            json={"title": title, "permissions": permissions, "expires_at": expiry},
        )

    def all(self) -> ApiResponse:
        return self._get("/tokens")

    def delete(self, token_id: int) -> ApiResponse:
        return self._delete(f"/tokens/{token_id}")

    def routes(self) -> ApiResponse:
        """Every permission key a token may carry, straight from the
        product. The source of truth for the scope matrix."""
        return self._get("/routes")
