"""Projects, and everything whose permissions hang off a project.

The product's whole access model is rooted here: a task is reachable
because its project is, and a grant on a project is what every other
check ultimately consults. That makes this the busiest client in the
access matrix.

Note the verbs. v1 creates with PUT and updates with POST, which is the
reverse of the usual convention and one of the differences the
cross-version checks pin down.
"""

from __future__ import annotations

from typing import Any

from vikunja_qa.clients.base import DomainClient
from vikunja_qa.domain.permissions import Permission
from vikunja_qa.transport.response import ApiResponse


class ProjectsClient(DomainClient):
    # --- the project itself -------------------------------------------------

    def create(self, title: str, **fields: Any) -> ApiResponse:
        return self._put("/projects", json={"title": title, **fields})

    def get(self, project_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}")

    def all(self, **params: Any) -> ApiResponse:
        return self._get("/projects", params=params or None)

    def update(self, project_id: int, **fields: Any) -> ApiResponse:
        return self._post(f"/projects/{project_id}", json=fields)

    def delete(self, project_id: int) -> ApiResponse:
        return self._delete(f"/projects/{project_id}")

    def duplicate(self, project_id: int, **fields: Any) -> ApiResponse:
        return self._put(f"/projects/{project_id}/duplicate", json=fields)

    # --- grants to users ----------------------------------------------------

    def add_user(
        self, project_id: int, username: str, permission: Permission = Permission.READ
    ) -> ApiResponse:
        return self._put(
            f"/projects/{project_id}/users",
            json={"username": username, "permission": int(permission)},
        )

    def set_user_permission(
        self, project_id: int, username: str, permission: Permission
    ) -> ApiResponse:
        return self._post(
            f"/projects/{project_id}/users/{username}",
            json={"permission": int(permission)},
        )

    def remove_user(self, project_id: int, username: str) -> ApiResponse:
        return self._delete(f"/projects/{project_id}/users/{username}")

    def users(self, project_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}/users")

    # --- grants to teams ----------------------------------------------------

    def add_team(
        self, project_id: int, team_id: int, permission: Permission = Permission.READ
    ) -> ApiResponse:
        return self._put(
            f"/projects/{project_id}/teams",
            json={"team_id": team_id, "permission": int(permission)},
        )

    def set_team_permission(
        self, project_id: int, team_id: int, permission: Permission
    ) -> ApiResponse:
        return self._post(
            f"/projects/{project_id}/teams/{team_id}",
            json={"permission": int(permission)},
        )

    def remove_team(self, project_id: int, team_id: int) -> ApiResponse:
        return self._delete(f"/projects/{project_id}/teams/{team_id}")

    def teams(self, project_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}/teams")

    # --- views and kanban buckets -------------------------------------------

    def views(self, project_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}/views")

    def buckets(self, project_id: int, view_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}/views/{view_id}/buckets")

    def create_bucket(self, project_id: int, view_id: int, title: str) -> ApiResponse:
        return self._put(f"/projects/{project_id}/views/{view_id}/buckets", json={"title": title})

    def delete_bucket(self, project_id: int, view_id: int, bucket_id: int) -> ApiResponse:
        """The operation CVE-2026-55065 was about: it must refuse a caller
        with no rights on the owning project."""
        return self._delete(f"/projects/{project_id}/views/{view_id}/buckets/{bucket_id}")

    # --- webhooks -----------------------------------------------------------

    def create_webhook(self, project_id: int, target_url: str, events: list[str]) -> ApiResponse:
        return self._put(
            f"/projects/{project_id}/webhooks",
            json={"target_url": target_url, "events": events},
        )

    def webhooks(self, project_id: int) -> ApiResponse:
        return self._get(f"/projects/{project_id}/webhooks")
