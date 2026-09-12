# VKJ-010. A failed file upload returns status 200

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** attachment upload while the object store is unavailable
**Environment:** official image `vikunja/vikunja:2.6.0`, file storage in S3-compatible MinIO, the stand from `docker/docker-compose.yml`

## Summary

If the object store is unavailable, the attachment upload fails, but the response comes back with **200 OK**. The sign of the failure is hidden in the body:

```
HTTP/1.1 200 OK
{"errors":[{"message":"failed to save file: failed to upload file to S3: operation error S3 ..."}]}
```

On top of that, the response only arrives after **28 seconds**: the client holds the connection open for the whole of it.

## Impact

The status code is the first and often the only thing a client looks at. Libraries raise an exception from it, generated clients branch on it, queues and retries decide the fate of a job by it. A 200 here means the caller counts the file as saved.

The consequence for the user is direct: the interface shows success, the attachment disappears, and the person sees no error. Data is lost silently, and that is the worst kind of loss, because nobody learns of it in time.

Twenty-eight seconds of a held connection makes it worse: under bulk uploading the connection pool is used up entirely.

## What does work correctly

Worth noting, because it shows that the product does isolate its dependencies in principle. With the same store switched off, creating a task, which needs no files, finished in a tenth of a second and returned 201. So a storage outage does not bring the whole product down; the problem is precisely in the report of the result.

## Steps to reproduce

1. Bring the stand up.
2. Stop the storage container: `docker compose stop minio`.
3. Upload an attachment to a task through the API.
4. Look at the status code and at the body.
5. Bring the container back: `docker compose start minio`.

The test `tests/resilience/dependencies/test_object_storage.py` does all of it and restores the stand itself.

## Expected

A failed upload answers with a code from the error range, preferably 502 or 503, since the cause is an external dependency.

## Actual

200, with a description of the error in the body.

## What to fix

Return an error code when saving the file fails. Separately, the wait is worth shortening: twenty-eight seconds is probably the sum of the S3 client's retries, and it should be bounded.

## Related test

`tests/resilience/dependencies/test_object_storage.py::test_a_failed_upload_says_so_in_its_status_code`, marked as an expected failure. It states the position without breaking the build, and turns into an unexpected pass once the status code is fixed.
