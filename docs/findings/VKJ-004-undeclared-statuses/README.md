# VKJ-004. Operations answer with statuses that are not in their specification

English | [Русский](README.ru.md)

**Severity:** low
**Version:** Vikunja v2.6.0
**Component:** the API specification
**Environment:** official image `vikunja/vikunja:2.6.0`, the stand from `docker/docker-compose.yml`

## Summary

Some operations return response codes that are not listed in their specification. Found on a sample of 32 calls, so it happens often.

| Operation | Status | What is declared |
|---|---|---|
| `GET /api/v1/user` | 401 | 200, 404, 500 |
| `GET /api/v1/user/settings/totp` | 412 | no 412 |

The `GET /user` case is telling: it is a protected endpoint, and 401 on it is not an edge case but the normal answer to a missing or expired token.

## Impact

A consumer of the specification does not know which errors to handle. A generated client lands in its "unexpected response" branch on the most ordinary scenario there is, an expired session. The API documentation misleads in exactly the part that is needed most during integration.

## Reproduction

```bash
python reproduce.py
```

## What to fix

Add 401 to every protected operation in the specification, and 412 where a precondition is checked. Since 401 applies to the whole protected surface, it makes more sense to describe it once as a shared response than to list it in every operation.

## Related test

Caught by the contract check in the transport layer, violation kind "undeclared status". Recorded in the baseline as `VKJ-004`.

An important caveat: this is the only baseline entry that covers a whole kind of violation rather than a specific pattern. New cases of the same kind will therefore not break the build. The entry will narrow to a list of specific operations once the suite walks every operation with a generated family and the full list is known.
