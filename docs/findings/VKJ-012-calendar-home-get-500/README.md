# VKJ-012. GET on the CalDAV calendar home answers 500

English | [Русский](README.ru.md)

**Severity:** low
**Version:** Vikunja v2.6.0
**Component:** CalDAV, the calendar home collection `/dav/projects/`
**Environment:** official image `vikunja/vikunja:2.6.0`, CalDAV enabled (the default), the stand from `docker/docker-compose.yml`

## Summary

A signed-in `GET` or `HEAD` on the calendar home, `/dav/projects/` with or without the trailing slash, answers **500 Internal Server Error** with an empty body. `PROPFIND` on the same collection, with the same credentials, answers 207 and lists the projects.

```
PROPFIND /dav/projects/   207   286 bytes
GET      /dav/projects/   500     0 bytes
HEAD     /dav/projects/   500     0 bytes
GET      /dav/projects    500     0 bytes
```

The product logs these requests at INFO level with no error attached, so the failure does not show up in the logs either.

## Impact

Calendar clients discover collections with `PROPFIND`, so ordinary synchronisation never takes this path. That is why the severity is low.

Everything else that touches the URL does. A person opening the CalDAV address from the settings page in a browser, a generic WebDAV client, a monitoring probe or a reverse proxy health check all get a server error. The operator then finds nothing in the logs to explain it, and the 500 is counted as a server fault by any alerting built on status codes.

## Steps to reproduce

1. Bring the stand up.
2. Register and confirm an account.
3. Send `GET /dav/projects/` with HTTP Basic credentials for that account.
4. Send `PROPFIND /dav/projects/` with `Depth: 1` and the same credentials, for comparison.

`reproduce.py` in this folder does all of it with the standard library only:

```bash
py docs/findings/VKJ-012-calendar-home-get-500/reproduce.py
```

## Expected

A `GET` on a collection answers with content, or with 404 or 405 if the server does not serve one. It does not answer 500.

## Actual

500 with an empty body, for `GET` and `HEAD`, with and without the trailing slash.

## Cause, read from the source

`ProjectHandler` serves both `/dav/projects` and `/dav/projects/:project`. With no project in the path, `getProjectFromParam` returns an empty project whose ID is 0. On `GET`, `GetResource` runs the collection read check on it, `CanRead` looks the project up, and `requireProjectsByIDs` fails with `ErrProjectDoesNotExist{ID: 0}`. That is not the not-found error caldav-go understands, and caldav-go turns any other storage error into 500. The storage code says as much in a comment of its own.

`PROPFIND` never reaches that check: `GetResources` has a branch for the home collection.

## What to fix

Handle the home collection explicitly on `GET` and `HEAD`, as `PROPFIND` already does: answer 405, or an empty calendar. Separately, logging the underlying error when caldav-go produces a 500 would have made this visible to operators.

## Related test

`tests/api/calendar/test_calendar_access.py::test_the_calendar_home_answers_a_plain_get_without_a_server_error`, marked as an expected failure. It states the position without breaking the build, and turns into an unexpected pass once the home stops answering 500.
