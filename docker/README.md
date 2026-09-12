# The stand

English | [Русский](README.ru.md)

Eight containers, brought up with one command. The system under test is Vikunja 2.6.0.

## Running it

```bash
docker compose up -d --quiet-pull
python ../scripts/check_stand.py
```

The second step is not optional. It waits for every service and walks one real user path end to end, so a green result actually means something. Tests must not be started without it: `docker compose up` returns before the application is ready to answer.

Stopping and removing the data:

```bash
docker compose down -v
```

## What listens where

| Service | Port | What for |
|---|---|---|
| vikunja | 3456 | the system under test |
| postgres | 15432 | direct queries for the integrity checks |
| redis | 16379 | the key-value store and the rate limiter's counters |
| minio | 19000, 19001 | object storage for files, and its console |
| mailpit | 18025, 11025 | the mail trap: an API for reading messages, and SMTP |
| webhook receiver | 18080 | recording outgoing calls |
| prometheus | 19090 | scraping the application's metrics |
| grafana | 13000 | the dashboard, anonymous sign-in |

**Why these ports.** All of them are below 49152. On Windows the dynamic port range is reserved for Hyper-V, and landing in it gives a socket bind failure with an unhelpful message about permissions. The reserved ranges can be listed with:

```bash
netsh int ipv4 show excludedportrange protocol=tcp
```

## The settings, and why they are what they are

**Rate limiting is switched off.** Otherwise a parallel run walks straight into the product's own limit. The tests for rate limiting itself bring up a separate profile with it enabled.

**The floors for pre-authentication routes are raised separately.** That is not the same as the global switch. The product keeps a floor of ten requests a minute per address on routes reached before authentication, and it **deliberately ignores the global flag**, as a comment in the source says outright:

> pre-auth routes need a floor even with the global limiter off, which is the default

Every account the suite creates costs three such calls: registration, address confirmation and sign-in. At the default floor the suite could create three accounts a minute, which would not cover the warm-up. So `VIKUNJA_RATELIMIT_NOAUTHLIMIT` is raised on the stand, along with the floors for basic authentication and token refresh. In the profile for the rate-limiting tests they stay as they really are.

**Files go to object storage rather than to disk.** That is the longer path through the product's code, and the closer one to a production deployment.

**Mail is enabled and goes to the trap.** One consequence matters: with a mailer configured, Vikunja holds a new account until its address is confirmed. The tests go through that confirmation the real way, reading the message out of the trap. The full round trip takes about 0.4 seconds, so a back door through the database is not needed.

**The product's testing API is enabled by a secret.** It offers truncating every table and filling one table with given contents. It is used in exactly two cases: a single reset before a run, and preparing states the public API cannot reach. Ordinary data is prepared with ordinary calls.

**Calls to non-routable addresses are allowed.** The webhook receiver lives on Compose's private network, and without that flag the product refuses to knock on it.

**CalDAV is enabled**, which is the product's default. It is the second door onto the same data, and the suite checks that both doors agree.

## The descriptions

Both API versions serve their own description from the live instance:

| Version | Path | Format | Paths |
|---|---|---|---|
| v1 | `/api/v1/docs.json` | Swagger 2.0 | 126 |
| v2 | `/api/v2/openapi.json` | OpenAPI 3.1.0 | 133 |

The descriptions are fetched from the instance rather than from the product's repository, so the version being checked is exactly the version that is up.

## Diagnostics

The application's logs:

```bash
docker compose logs vikunja -f
```

The Docker Desktop interface gives the same thing with a mouse, plus a terminal inside a container and a look at its files. For the resilience checks it is also a convenient place to stop a container by hand.

Mail can be read at `http://localhost:18025`, object storage at `http://localhost:19001` with the credentials `minioadmin` and `minioadmin`, and the dashboard at `http://localhost:13000`.

Recorded webhooks are read like this:

```bash
curl http://localhost:18080/_recorded
```

Every test sends its webhooks to a path of its own, `/hook/<test identifier>`, so recordings do not mix in a parallel run.
