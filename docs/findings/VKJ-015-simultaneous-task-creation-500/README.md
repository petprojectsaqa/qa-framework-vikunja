# VKJ-015. Two people adding a task to the same project at once: one gets a 500

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** task creation, the per-project task number (`pkg/models/tasks.go`)
**Environment:** official image `vikunja/vikunja:2.6.0`, PostgreSQL, the stand from `docker/docker-compose.yml`

## Summary

Tasks created in the same project at the same moment collide on the per-project number. One caller wins. Every other caller gets **500 Internal Server Error**, and their task is not created.

Six callers, one project, released together:

```
all in one project     {201: 1, 500: 5}
one project each       {201: 6}
```

The control matters: the same six callers writing into six different projects all succeed. The contention is per project, and it does not need six callers. **Two are enough**, and two is the everyday case.

The body the loser receives says nothing useful:

```
HTTP/1.1 500 Internal Server Error
{"message":"Internal Server Error"}
```

The server log names the cause:

```
pq: duplicate key value violates unique constraint "UQE_tasks_tasks_project_index" (23505)
```

## Impact

This is not a load-test artefact. A shared project is the ordinary use of the product, and two people pressing "add task" in the same second is the ordinary thing for them to do. One of them loses their task and is told the server broke.

Nothing is corrupted: the tasks that are created keep distinct numbers, and the database constraint is exactly what prevents worse. The cost falls entirely on the caller who is refused, and on whoever has to explain the 500.

It also makes the product unsafe to drive concurrently from anything else: an importer, a synchronising client, or a browser tab that creates several tasks at once will lose some of them. Retrying is possible, but nothing in the answer says it is worth retrying: a 500 is the status clients are least likely to retry.

## Cause, read from the source

`createTasks` assigns the number through `setNewTaskIndexes`, which calls `calculateNextTaskIndex` to read the highest number in the project and adds one:

```go
func setNewTaskIndexes(s *xorm.Session, projectID int64, tasks []*Task) (err error) {
	nextIndex, err := calculateNextTaskIndex(s, projectID)
	...
	t.Index = nextIndex
```

Read, then insert, with nothing serialising the pair. Two transactions read the same highest number, compute the same next one, and the second insert meets the unique constraint `UQE_tasks_tasks_project_index`. The error is returned as-is, so it reaches the client as a 500.

## Steps to reproduce

1. Bring the stand up and register an account.
2. Create one project.
3. Send several `PUT /api/v1/projects/{id}/tasks` requests released at the same instant, each from its own connection.
4. Compare with the same number of requests spread over separate projects.

`reproduce.py` in this folder does both, with a barrier so the calls really do overlap:

```bash
py docs/findings/VKJ-015-simultaneous-task-creation-500/reproduce.py
```

## Expected

Every caller's task is created, whoever else is writing at the time. If the product cannot serve them all, it answers something a client can act on, such as 409, rather than 500.

## Actual

All but one caller get 500 and their tasks do not exist.

## What to fix

Serialise the number's assignment: allocate it inside the same transaction under a lock on the project row, or use a sequence, or retry the insert on constraint 23505 rather than returning it. The retry is the smallest change and would make the collision invisible, which is what a client has a right to expect from a number the server chooses for it.

## Related test

`tests/api/concurrency/test_simultaneous_writes.py::test_tasks_created_at_the_same_moment_are_all_created`, marked as an expected failure. Its neighbours in the same module check what must hold regardless: the tasks that are accepted keep distinct numbers, simultaneous updates keep one of the writes, and neither a double delete nor a double label add answers with a server error.
