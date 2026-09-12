# VKJ-011. With Redis unavailable, requests do not fail, they hang

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** access to the key-value store
**Environment:** official image `vikunja/vikunja:2.6.0`, `VIKUNJA_REDIS_ENABLED=true` and `VIKUNJA_KEYVALUE_TYPE=redis`, the stand from `docker/docker-compose.yml`

**An important condition:** the finding applies to an installation where Redis is the chosen key-value store. That is a configuration the product supports, and the usual choice for installations running in several instances. With the default value, where the store is held in the memory of the process, the behaviour is different.

## Summary

If Redis stops answering, authenticated requests to the API **return nothing at all**. Measured on a clean stand:

| Request | Result |
|---|---|
| `GET /api/v1/projects/{id}` | no answer in 40 seconds |
| `GET /api/v1/user` | no answer in 40 seconds |

The request for one's own profile reads no project data, and it does not answer either. So what is affected is not one particular place but the common handling path.

## Why this matters more than ordinary degradation

A dependency failing is normal in itself, and one of two things is expected of a product: to work without it, or to fail clearly. Neither happens here.

Hanging is worse than failing. The connection is held, the handler is busy, and under ordinary load the pool is exhausted within seconds. The reverse proxy in front of the application starts piling requests up, the liveness check gets no answer, the orchestrator restarts the container, and the new instance runs into the same unavailable Redis. A single failure of an auxiliary store turns into a complete stop of the service.

For comparison, the product survives an object store failure correctly: creating a task with MinIO switched off finished in a tenth of a second. So the product does isolate its dependencies, and on this path that isolation is missing.

## Steps to reproduce

1. Bring up a stand where Redis is the chosen key-value store.
2. Register a user and get a token.
3. Stop the container: `docker compose stop redis`.
4. Make any authenticated request with a time limit of forty seconds.
5. Bring the container back: `docker compose start redis`.

## Expected

The request finishes: either successfully, if the data from the key-value store is not required, or with an error within a reasonable time.

## Actual

No response arrives within forty seconds.

## What to fix

Bound the time spent talking to the key-value store, and when that time runs out either carry on without it or fail with a clear code. A cache is optional by its nature, and its unavailability should not block handling.

## Related test

`tests/resilience/dependencies/test_key_value_store.py::test_losing_redis_degrades_requests_instead_of_hanging_them`, marked as an expected failure.
