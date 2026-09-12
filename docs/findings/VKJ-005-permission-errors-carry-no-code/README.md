# VKJ-005. Permission errors carry no domain code for a client to translate by

English | [Русский](README.ru.md)

**Severity:** medium
**Version:** Vikunja v2.6.0
**Component:** error handling, both API versions
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

The product has a numeric domain error code, and clients use it to pick the translation of the message. Missing objects return meaningful codes. Permission refusals return nothing useful:

| Request | Status | Domain code | Message |
|---|---|---|---|
| `GET /api/v1/tasks/{someone else's}` | 403 | `0` | You don't have the permission to see this |
| `GET /api/v1/tasks/{missing}` | 404 | `4002` | This task does not exist |
| `GET /api/v1/projects/{someone else's}` | 403 | `0` | You don't have the permission to see this |
| `GET /api/v1/projects/{missing}` | 404 | `3001` | This project does not exist. |
| `DELETE /api/v1/tasks/{someone else's}` | 403 | `0` | Forbidden |
| `GET /api/v2/tasks/{someone else's}` | 403 | no field | You don't have the permission to see this |

The first version returns a zero, the second returns no field at all. The second version's code does take separate care to carry the domain code across into the response, with a comment beside it explaining that without that step clients read a zero. The mechanism exists, then, but it does not extend to the permission-refusal path, because there is nothing to carry across.

## Impact

A permission refusal is one of the most common errors a live user sees. It is precisely the one a client cannot translate: a zero code is indistinguishable from no code at all, and translating by the text of the message is not an option. In an interface in any language other than English, the user gets an English string from the server.

Telling the cases apart suffers as well. Every refusal arrives with a zero, so a client cannot distinguish no rights to the object from no rights to the action, and cannot show different hints for them.

## Steps to reproduce

```bash
python reproduce.py
```

The script creates two users, creates a project and a task as the first, and queries them as the second, printing the codes side by side.

## Expected

A permission error has a non-zero domain code of its own, as a not-found error does.

## Actual

A zero in the first version, no field at all in the second.

## What to fix

Give permission refusals domain codes of their own, and put them through the same carry-across that is already done for the other errors in the second version.

## Related test

`tests/api/contracts/test_error_codes.py::test_a_refusal_carries_no_usable_code`. The test asserts the current behaviour deliberately, so that a fix does not go unnoticed: once the codes appear it turns red, and its message says the finding is probably closed.
