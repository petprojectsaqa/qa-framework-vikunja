"""The product's permission ladder.

Three levels, plus a fourth state the product uses internally for
"not determined". That fourth one matters to the suite: it serialises to
JSON null, which the v1 description does not admit, and that is half of
finding VKJ-002.
"""

from __future__ import annotations

from enum import IntEnum


class Permission(IntEnum):
    READ = 0
    WRITE = 1
    ADMIN = 2

    def __str__(self) -> str:
        return self.name.lower()


#: What the product sends when a permission could not be determined.
#: Not a member of the enum because it never appears in a valid grant.
UNKNOWN = -1

#: Everything a test may hand out, in ascending order.
ALL: tuple[Permission, ...] = (Permission.READ, Permission.WRITE, Permission.ADMIN)
