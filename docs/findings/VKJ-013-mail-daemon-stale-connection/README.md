# VKJ-013. Mail stops for good after the mail server restarts, unless traffic pauses

English | [Русский](README.ru.md)

**Severity:** high
**Version:** Vikunja v2.6.0
**Component:** the outgoing mail daemon (`pkg/mail/mail.go`)
**Environment:** official image `vikunja/vikunja:2.6.0`, mailer enabled, the stand from `docker/docker-compose.yml`

## Summary

If the SMTP server restarts, or drops the connection for any reason, Vikunja's mail daemon does not reconnect while mail keeps flowing. It holds the connection it opened before, tries every queued message on that dead connection, and each one fails. It only re-dials once its queue has been **idle for the 30-second `mailer.queuetimeout`**.

So the recovery depends on the traffic, not on the server coming back. On a quiet instance a single later message reconnects and gets through. On a busy one, where messages arrive less than 30 seconds apart, the idle timer never fires, and **every message is lost for as long as the traffic continues** — confirmations, password resets, reminders, all of it, silently.

Measured on the stand, one registration every 5 seconds after the mail server came back:

```
delivered while traffic continued (25s):  no
delivered after a 35s idle gap:           yes
```

The product logs each failure, so it is visible to an operator watching the logs, but nothing surfaces to the user or retries the lost message:

```
level=ERROR msg="Error when sending mail: checking SMTP connection: not connected to SMTP server"
```

## Impact

The busier the instance, the worse and the longer the outage: exactly backwards from what an operator would expect. A mail server blip that should cost a few seconds of delay instead costs every email until traffic happens to fall quiet for half a minute, which on an active instance may be a long time coming. Nothing is retried, so the messages sent in that window are gone.

Password resets and address confirmations are the messages users are actively waiting on, so this reads to them as an account they can no longer get into.

## Cause, read from the source

`StartMailDaemon` in `pkg/mail/mail.go` runs one goroutine around a `select`. A message dials the connection if `open` is false, then sends; a 30-second timeout with no message closes the connection and sets `open = false`.

```go
case m, ok := <-queue:
    ...
    if !open {
        err = c.DialWithContext(context.Background())
        ...
        open = true
    }
    err = c.Send(m)
    if err != nil {
        log.Errorf("Error when sending mail: %s", err)
        break            // leaves open == true
    }
case <-time.After(config.MailerQueueTimeout.GetDuration() * time.Second):
    if open {
        open = false     // the only path that clears it
        c.Close()
    }
```

A send failure logs and breaks, but leaves `open` true, so the next message skips the redial and sends on the same dead connection. The only thing that ever clears `open` is the idle timeout, and steady traffic keeps re-arming that timer before it can fire.

## Steps to reproduce

1. Bring the stand up and confirm mail is delivered.
2. `docker compose stop mailpit`, then `docker compose start mailpit`.
3. Trigger an email (register an account, or request a password reset) every few seconds for half a minute. None arrive.
4. Stop triggering for more than 30 seconds, then trigger one more. It arrives.

`reproduce.py` in this folder does all of it, driving the stand's mail server up and down, and prints the two outcomes:

```bash
py docs/findings/VKJ-013-mail-daemon-stale-connection/reproduce.py
```

## Expected

Once the mail server is reachable again, queued and subsequent mail is delivered, within a bound that does not depend on traffic falling silent.

## Actual

While mail keeps flowing at less than one message per 30 seconds, none is delivered. Only a 30-second idle gap lets the daemon reconnect.

## What to fix

Clear `open` (and close the connection) on a send failure, so the next message re-dials. A reconnect with a short backoff on the send path would turn a mail-server blip into a brief delay rather than an open-ended outage. Failed messages could also be requeued rather than dropped.

## Related test

`tests/resilience/dependencies/test_mail.py::test_mail_recovers_after_the_server_returns_even_under_traffic`, in the resilience layer and marked as an expected failure. It states the position without breaking the build and turns into an unexpected pass once recovery no longer depends on an idle gap.
