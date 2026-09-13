# VKJ-017. Updating one project rewrites every project on the instance

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** projects, the update path
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

Renaming a project — any single-field update — makes the product rewrite the `position` and `updated` columns of **every project row in the database**, including projects owned by accounts that have nothing to do with the one making the change.

Measured on a stand with 12 848 projects belonging to 9 449 accounts. One rename:

| | |
|---|---|
| rows whose `updated` changed | **12 847** of 12 848 |
| distinct owners whose projects were rewritten | **9 449** |
| the renamed project itself among them | no |
| how long the request took | **4.94 s** |

The database shows the shape plainly. Sampling `pg_stat_activity` during the request finds one statement, run over and over:

```sql
UPDATE "public"."projects" SET "position" = $1, "updated" = $2 WHERE (id = $3)
```

One statement per project, not one for the project being changed.

The cost is linear in the number of projects the instance holds, and has nothing to do with the project being edited or with who owns it:

| projects on the instance | one rename takes | rows rewritten |
|---|---|---|
| 10 | 0.017 s | 8 |
| 100 | 0.056 s | 100 |
| 500 | 0.194 s | 496 |
| 1 500 | 0.587 s | 1 500 |
| 12 848 | 4.940 s | 12 847 |

About 0.4 ms of every rename belongs to each project already on the instance. Creating a project costs 57 ms and reading one 7 ms, at any size — it is the update path alone.

## Impact

Three consequences, in ascending order of how hard they are to live with.

**It gets slower without bound.** At ten thousand projects a rename takes five seconds. There is no size at which it levels off, because the work is proportional to the table.

**It writes to other tenants' rows.** `updated` is a field the API returns and clients read. A user who has not touched their project for a year sees it modified because an unrelated account, in an unrelated organisation, renamed something. Any client that syncs on modification time — the product's own CalDAV door among them — is told everything changed. `position`, which decides the order projects appear in, is rewritten for everyone at the same time.

**It makes writes contend.** Thousands of row updates in one request means the lock footprint of a rename covers the whole table. Concurrent writers queue behind each other, and on a busy instance a rename can exceed a client's timeout entirely. That is how this was found: a test that archives a project began to fail intermittently under eight parallel workers, once the stand had accumulated enough projects.

## Reproduction

```bash
py docs/findings/VKJ-017-project-update-rewrites-every-project/reproduce.py
```

The script needs no database access and takes about thirty seconds. It registers two accounts, has the first rename its own project, and then reads the second account's project back through the API to show its `updated` and `position` have changed. It then creates five hundred more projects and repeats the same rename to show the same call has become measurably slower.

## What to fix

Renaming should update one row. If a position has to be assigned, assign it to the project being changed; the other rows already have positions and did not ask for new ones.

The general fix is the usual one for this shape: give `position` a sparse ordering so a single item can be placed between its neighbours without renumbering the rest, and recalculate the whole set only when the gaps genuinely run out. Whatever the scheme, the recalculation must be scoped to the projects the caller can see. Reaching across accounts is the part that is wrong regardless of performance.

## Scope of the finding

Only project updates. Creating a project does not do it, nor does reading one, nor does updating a task. The suite's other write paths were measured at the same instance size and stayed in the tens of milliseconds.

## Related test

`tests/api/integrity/test_data_integrity.py::test_a_write_by_one_account_leaves_another_accounts_projects_alone`, marked as an expected failure. It states the property the product should have — one account's write does not modify another's rows — so the day it is fixed the test becomes an unexpected pass and says so.
