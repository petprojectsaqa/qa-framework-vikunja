"""Tasks and everything hanging off them.

Attachments, comments, relations and reactions all live here because
each is a separate permission check in the product, and three of them
have appeared in published advisories.
"""

from __future__ import annotations

from typing import Any

from vikunja_qa.clients.base import DomainClient
from vikunja_qa.transport.response import ApiResponse


class TasksClient(DomainClient):
    # --- the task itself ----------------------------------------------------

    def create(self, project_id: int, title: str, **fields: Any) -> ApiResponse:
        return self._put(f"/projects/{project_id}/tasks", json={"title": title, **fields})

    def get(self, task_id: int) -> ApiResponse:
        return self._get(f"/tasks/{task_id}")

    def all(self, **params: Any) -> ApiResponse:
        return self._get("/tasks", params=params or None)

    def in_project(self, project_id: int, view_id: int, **params: Any) -> ApiResponse:
        return self._get(f"/projects/{project_id}/views/{view_id}/tasks", params=params or None)

    def update(self, task_id: int, **fields: Any) -> ApiResponse:
        return self._post(f"/tasks/{task_id}", json=fields)

    def delete(self, task_id: int) -> ApiResponse:
        return self._delete(f"/tasks/{task_id}")

    def bulk_update(self, task_ids: list[int], **fields: Any) -> ApiResponse:
        """Applies one change across several tasks.

        A prime suspect for partial-authorization defects: the check has
        to hold for every identifier in the list, not just the first.
        """
        return self._post("/tasks/bulk", json={"task_ids": task_ids, **fields})

    # --- attachments --------------------------------------------------------

    def attach(self, task_id: int, filename: str, content: bytes) -> ApiResponse:
        return self._put(
            f"/tasks/{task_id}/attachments",
            files={"files": (filename, content, "application/octet-stream")},
        )

    def attachments(self, task_id: int) -> ApiResponse:
        return self._get(f"/tasks/{task_id}/attachments")

    def attachment(self, task_id: int, attachment_id: int) -> ApiResponse:
        """The read CVE-2026-33678 was about: it used to resolve the
        attachment by its own identifier alone, without checking that it
        belonged to the task in the path."""
        return self._get(f"/tasks/{task_id}/attachments/{attachment_id}")

    def delete_attachment(self, task_id: int, attachment_id: int) -> ApiResponse:
        return self._delete(f"/tasks/{task_id}/attachments/{attachment_id}")

    # --- comments -----------------------------------------------------------

    def comment(self, task_id: int, text: str) -> ApiResponse:
        return self._put(f"/tasks/{task_id}/comments", json={"comment": text})

    def comments(self, task_id: int) -> ApiResponse:
        return self._get(f"/tasks/{task_id}/comments")

    def delete_comment(self, task_id: int, comment_id: int) -> ApiResponse:
        return self._delete(f"/tasks/{task_id}/comments/{comment_id}")

    # --- labels and assignees ----------------------------------------------

    def add_label(self, task_id: int, label_id: int) -> ApiResponse:
        return self._put(f"/tasks/{task_id}/labels", json={"label_id": label_id})

    def labels(self, task_id: int) -> ApiResponse:
        return self._get(f"/tasks/{task_id}/labels")

    def assign(self, task_id: int, user_id: int) -> ApiResponse:
        return self._put(f"/tasks/{task_id}/assignees", json={"user_id": user_id})

    def assignees(self, task_id: int) -> ApiResponse:
        return self._get(f"/tasks/{task_id}/assignees")

    # --- relations ----------------------------------------------------------

    def relate(self, task_id: int, other_task_id: int, kind: str = "related") -> ApiResponse:
        """Relations can cross project boundaries, so this is where a
        caller might reach a task they have no rights on."""
        return self._put(
            f"/tasks/{task_id}/relations",
            json={"other_task_id": other_task_id, "relation_kind": kind},
        )

    # --- reactions ----------------------------------------------------------

    def react(self, kind: str, entity_id: int, value: str) -> ApiResponse:
        """The entity type arrives in the path, which makes this the one
        polymorphic surface in the API."""
        return self._put(f"/{kind}/{entity_id}/reactions", json={"value": value})

    def reactions(self, kind: str, entity_id: int) -> ApiResponse:
        return self._get(f"/{kind}/{entity_id}/reactions")
