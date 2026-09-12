"""Direct access to the product's database.

For the claims the API cannot settle. When a delete is supposed to take
its children with it, or a rejected bulk operation is supposed to have
applied nothing, the API can only report what it chooses to report;
counting rows is the only way to know.

Read-only by design. The suite never writes here: building state through
anything but the product's own API would test the schema rather than the
product, and would rot at the first migration.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import allure
import psycopg
from psycopg.rows import dict_row

from vikunja_qa import reporting


class Database:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def _cursor(self) -> Iterator[psycopg.Cursor[dict[str, Any]]]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as connection:
            # Belt and braces: the suite has no reason to write, so make a
            # stray write fail loudly rather than quietly corrupt a run.
            connection.read_only = True
            with connection.cursor() as cursor:
                yield cursor

    # --- raw access ---------------------------------------------------------

    def rows(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with allure.step(f"query: {' '.join(sql.split())[:110]}"):
            with self._cursor() as cursor:
                cursor.execute(sql, params or {})
                result = cursor.fetchall()
            reporting.attach("\n".join(str(row) for row in result[:20]) or "(no rows)", name="rows")
            return list(result)

    def one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        found = self.rows(sql, params)
        return found[0] if found else None

    def count(self, sql: str, params: dict[str, Any] | None = None) -> int:
        row = self.one(sql, params)
        if row is None:
            return 0
        return int(next(iter(row.values())))

    # --- the questions the suite actually asks ------------------------------

    def tasks_in_project(self, project_id: int) -> int:
        return self.count(
            "select count(*) from tasks where project_id = %(project)s",
            {"project": project_id},
        )

    def task_titles_in_project(self, project_id: int) -> list[str]:
        return [
            str(row["title"])
            for row in self.rows(
                "select title from tasks where project_id = %(project)s order by id",
                {"project": project_id},
            )
        ]

    def task(self, task_id: int) -> dict[str, Any] | None:
        return self.one("select * from tasks where id = %(id)s", {"id": task_id})

    def project(self, project_id: int) -> dict[str, Any] | None:
        return self.one("select * from projects where id = %(id)s", {"id": project_id})

    def project_permissions(self, project_id: int) -> list[dict[str, Any]]:
        return self.rows(
            "select user_id, permission from users_projects where project_id = %(project)s"
            " order by user_id",
            {"project": project_id},
        )

    def attachments_of(self, task_id: int) -> list[dict[str, Any]]:
        return self.rows(
            "select id, file_id from task_attachments where task_id = %(task)s order by id",
            {"task": task_id},
        )

    def file_row(self, file_id: int) -> dict[str, Any] | None:
        return self.one("select * from files where id = %(id)s", {"id": file_id})

    def api_token_columns(self) -> list[str]:
        """Column names of the token table.

        Used to assert that no column holds a token in the clear.
        """
        return [
            str(row["column_name"])
            for row in self.rows(
                "select column_name from information_schema.columns"
                " where table_name = 'api_tokens' order by ordinal_position"
            )
        ]
