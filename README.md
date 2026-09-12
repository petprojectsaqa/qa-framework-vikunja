# qa-framework-vikunja

**English** · [Русский](README.ru.md)

[![suite](https://github.com/petprojectsaqa/qa-framework-vikunja/actions/workflows/suite.yml/badge.svg)](https://github.com/petprojectsaqa/qa-framework-vikunja/actions/workflows/suite.yml)
[![report](https://img.shields.io/badge/allure-report-green)](https://petprojectsaqa.github.io/qa-framework-vikunja/)

A reference API and UI test framework in Python, exercised against a real product: [Vikunja](https://github.com/go-vikunja/vikunja), a self-hosted task manager, pinned at v2.6.0 and run on an eight-container local stand.

This is not a collection of CRUD checks against a public sandbox. It is about the parts that usually get skipped: isolation that survives full parallelism, contract validation that costs nothing per test, an access matrix driven by data, verification through the database and the services around the product, and a comparison of the two API versions the product ships side by side.

**Eleven defects found in the product**, each with a reproduction that runs in seconds and imports nothing from this framework. See [docs/findings](docs/findings/).

**AI-first engineering.** This framework was built the way I work: with AI in the loop. AI speeds up implementation and widens the search for defects, while the architecture, the test strategy and every trade-off are engineering decisions, each written down in [docs/strategy.md](docs/strategy.md) with the alternatives it was chosen over. That combination is what lets one engineer deliver this depth of coverage: most of the suite is generated from the product's own API descriptions, and it has already found eleven real defects.

## Status

| | |
|---|---|
| Tests in the main run | 853 |
| Generated from the product's own descriptions | 762 |
| Run time on eight workers | about 50 seconds |
| API operations exercised | 99% of both versions |
| Framework unit tests, no stand needed | 27 in 3 seconds |
| Defects found in the product | 11 |

One item of the coverage matrix is still open: a thin slice of CalDAV, eight checks.

## Quick start

You need Docker with Compose, and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
```

```bash
docker compose -f docker/docker-compose.yml up -d --quiet-pull
```

```bash
uv run python scripts/check_stand.py
```

```bash
uv run pytest -n 8
```

The readiness check is not optional: `docker compose up` returns before the product answers. The script waits for every service, locates both API descriptions and walks one real user path end to end, so a green result means the stand is actually usable.

Browser tests need a browser, installed once:

```bash
uv run playwright install chromium
```

The resilience group stops containers, so it stays out of the main run:

```bash
uv run pytest tests/resilience -m resilience -p no:randomly
```

## Design notes

**Isolation comes from ownership, not cleanup.** Everything in Vikunja belongs to a user, so each test works under freshly registered accounts, and accounts that have never met cannot see each other's data. That gives full parallelism with no truncation between tests. The product ships a test API that empties every table, and it is deliberately not used for this.

**Registration walks the real path.** The stand runs with mail enabled, so the product holds a new account until its address is confirmed. The suite reads the message from the mail trap, takes the token and spends it. The round trip costs about 0.4 seconds, so there is no reason to flip the account status in the database, and the mail pipeline stays under continuous test.

**Contract validation is a side effect.** Responses are checked against their schema in the transport layer, so every call made by every test is validated and no separate contract suite is needed. Both descriptions are fetched from the running instance rather than from the product's repository. On its first day the check found four defects in a sample of 32 calls.

**Strict mode, with known deviations in a baseline.** A deviation missing from the baseline fails the test that produced it. The baseline holds only findings already written up; each entry names its report and gives a reason. Entries added just to silence the suite are not allowed, and a test enforces that.

**Check lists come from the product, not from a hand-kept file.** The authorization sweep is generated from both API descriptions, and the token scope matrix from the permission catalogue the product publishes itself. An endpoint added tomorrow is covered on the next run, and no list can drift from reality.

**State is declared, not programmed.** A test describes the world it needs in one chain and a builder makes the calls. Link shares and team members become actors like anyone else, so a row of the access matrix does not care how its caller got in.

**What happens outside the response is checked too.** Mail is read from the trap, outgoing webhooks from a dedicated sink, files through object storage, counters from the metrics scrape, and data integrity through direct PostgreSQL queries. That is why the stand runs eight containers.

**There is not a single fixed pause.** Waiting polls a condition against an explicit deadline, and a timeout says what it was waiting for.

**The browser never signs in through the form.** The account is prepared over the API and its token placed in browser storage before the application boots, so a page opens directly where the test needs it. A test fails only when the thing it checks is broken.

**API tests never retry.** A flaky API test is either a defect in the test or a real race in the product, and both need investigating. Browser tests get one retry, used to capture a trace rather than to turn a run green.

**Open questions are not presented as settled.** Where the product's behaviour looks like a defect that cannot be proven, the test is marked as an expected failure. It states the position without breaking the build, and turns into an unexpected pass if the product changes.

The full reasoning, with the alternatives each decision was chosen over, is in [docs/strategy.md](docs/strategy.md), and scope and priorities are in [docs/coverage-matrix.md](docs/coverage-matrix.md). Both documents are currently in Russian.

## Layout

```
docker/     the eight-service stand and the webhook sink
docs/       coverage matrix, strategy, findings
scripts/    stand readiness check and the findings runner
src/        the framework
tests/      unit, smoke, api, ui, resilience
```

Layers inside `src` depend in one direction only: tests, scenes, area clients, transport, config. No assertion lives below the test layer.

## Findings

Eleven defects, each in its own folder with a reproduction:

```bash
python scripts/verify_findings.py
```

On Windows PowerShell, use `py` in place of `python`.

The scripts import nothing from the framework and need no dependencies, so a reviewer can confirm a finding without reading the code. The write-ups are currently in Russian; every reproduction prints its result in English.

## Report

The report of the latest run is published automatically at [petprojectsaqa.github.io/qa-framework-vikunja](https://petprojectsaqa.github.io/qa-framework-vikunja/). History is kept between runs, so trends are visible rather than only the last result.
