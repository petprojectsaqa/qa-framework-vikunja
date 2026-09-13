# VKJ-011. With Redis unavailable, requests wait without any bound the product sets

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** access to the key-value store
**Environment:** official image `vikunja/vikunja:2.6.0`, `VIKUNJA_REDIS_ENABLED=true` and `VIKUNJA_KEYVALUE_TYPE=redis`, the stand from `docker/docker-compose.yml`

**An important condition:** the finding applies to an installation where Redis is the chosen key-value store. That is a configuration the product supports, and the usual choice for installations running in several instances. With the default value, where the store is held in the memory of the process, the behaviour is different.

## Summary

If Redis stops answering, the first authenticated requests to the API **block until something outside the product gives up**. The product sets no bound of its own on the wait. Measured on a clean stand:

| Request | With Redis up | First calls with Redis stopped | Later calls |
|---|---|---|---|
| `GET /api/v1/user` | 0.01 s | no answer in 45 s | 0.08 s |
| `GET /api/v1/projects/{id}` | 0.04 s | no answer in 45 s | 0.26 s |

Two things in that table matter more than the headline number.

The request for one's own profile reads no project data, and it blocks too. So what is affected is not one particular place but the common handling path.

And the product does eventually shed the dependency: after the first attempts it stops waiting on the store and serves the rest in a quarter of a second. The defect is not that it cannot live without its cache — it can — but that it takes an unbounded amount of time to find that out, on every request in the meantime.

## What this depends on, and what it does not

**This finding was overstated when it was first written**, and the correction is worth stating plainly rather than quietly editing away. The original report said requests "return nothing at all", full stop, with no qualification. Running the reproduction on a Linux CI runner instead of Docker Desktop on Windows produced a 2-second answer rather than a hang, and the report as written did not survive that.

What varies is the *length* of the wait, and it is the host's doing, not the product's. A stopped container leaves its address unreachable, and how long a connection attempt to an unreachable address takes before it gives up is a property of the network stack in between:

| Where | With Redis up | First call with Redis stopped |
|---|---|---|
| Docker Desktop on Windows, through its port forwarder | 0.03 s | no answer in 25–45 s |
| a Linux CI runner, on the bridge directly | 0.00 s | 2.0 s |

What does not vary is the product's part: in both, a call on the common path waits for the network to decide, because the product asks it to. Two seconds on a login path is still enough to exhaust a connection pool under load, and forty is enough to fail a liveness check and have an orchestrator restart the container — into the same unavailable Redis.

So the finding stands, and its claim is now the one that reproduces everywhere: **the product puts no timeout of its own on the key-value store, on a path every authenticated request takes.** The reproduction asserts that, by comparison against the same call when the store is up, rather than asserting a number it cannot promise.

## Why this matters more than ordinary degradation

A dependency failing is normal in itself, and one of two things is expected of a product: to work without it, or to fail clearly, within a time it chooses. The product gets there in the end — it does work without the store — but not within any time of its own choosing.

Waiting is worse than failing, for as long as it lasts. The connection is held, the handler is busy, and under ordinary load the pool is exhausted in that window. The reverse proxy in front of the application starts piling requests up, the liveness check waits with everyone else, and where the wait is long enough the orchestrator restarts the container — into the same unavailable Redis.

For comparison, the product survives an object store failure correctly: creating a task with MinIO switched off finished in a tenth of a second. So the product does isolate its dependencies, and on this path that isolation is missing.

## Steps to reproduce

1. Bring up a stand where Redis is the chosen key-value store.
2. Register a user and get a token.
3. Stop the container: `docker compose stop redis`.
4. Make any authenticated request, timing it, with a generous time limit.
5. Repeat it twice more, timing each.
6. Bring the container back: `docker compose start redis`.

## Expected

Every request finishes within a time the product decides: successfully, if the key-value store is not needed for it, or with a clear error.

## Actual

The first requests take as long as the host takes to abandon the connection — two seconds on a Linux bridge, tens of seconds through Docker Desktop's port forwarder. The ones after them are served normally, the product having stopped waiting on the store by then.

## What to fix

Bound the time spent talking to the key-value store, and when that time runs out either carry on without it or fail with a clear code. A cache is optional by its nature, and its unavailability should not block handling.

## Related test

`tests/resilience/dependencies/test_key_value_store.py::test_losing_redis_degrades_requests_instead_of_hanging_them`, marked as an expected failure.
