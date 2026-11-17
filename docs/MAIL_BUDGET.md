# SMTP daily budget

Shifty applies an optional best-effort budget at the shared SMTP sink. This
does not guarantee the provider's account quota: it counts sends made through
Shifty, while other apps or manual sends using the same account are outside
the counter. `MAIL_DAILY_BUDGET` remains unset by default. The design target,
adopted by the owner in D-20261117-02 (`docs/DECISIONES.md`), is 250
admissions per day for the Brevo Free account reported at 300 emails per day. That leaves a 50-message margin for traffic Shifty cannot
count; it is not a hard provider limit. The reset hour and timezone are not
confirmed. Do not assume midnight UTC or enable the cap in production until
Brevo's Plan & Usage counter or support confirms the actual reset window.

With a 250-message target, the 20% critical reserve is 50 messages, the
noncritical ceiling is 200 admissions, and the 80% alert begins at 200 total
admissions. The tests exercise configured reset windows, but they do not
establish Brevo's actual reset time. The cap remains unset in production until
the provider window is confirmed.

The example values remain commented so copying `.env.example` does not turn
on the cap:

```dotenv
# MAIL_DAILY_BUDGET=250
# MAIL_CRITICAL_RESERVE_PERCENT=20
# MAIL_BUDGET_ALERT_PERCENT=80
```

Before enabling the cap, set `MAIL_BUDGET_TIMEZONE` and
`MAIL_BUDGET_RESET_HOUR` to the reset window confirmed by Brevo. These values
are intentionally absent from the example because the account's reset time
and timezone are not yet verified.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAIL_DAILY_BUDGET` | unset | Maximum admitted messages in one provider calendar window. Must be a positive integer when set. |
| `MAIL_BUDGET_ALERT_PERCENT` | `80` | Emit one Sentry warning when admitted messages first reach this percentage. |
| `MAIL_CRITICAL_RESERVE_PERCENT` | `20` | Keep this fraction of the cap available to critical messages. |
| `MAIL_BUDGET_TIMEZONE` | unset | IANA timezone used for the provider's calendar reset. Required with an enabled cap. |
| `MAIL_BUDGET_RESET_HOUR` | unset | Local hour, 0–23, when the provider quota window resets. Required with an enabled cap. |

When `MAIL_DAILY_BUDGET` is set, the application refuses to start unless both
the timezone and reset hour are provided. With the cap unset, UTC midnight is
used only to group internal metrics; it does not represent a provider reset.
The control only covers messages sent by Shifty processes that share the same
non-evicting Redis instance. An incorrect window or sends from outside Shifty
can still exceed the provider's quota.

The repository's `redis_state` Compose service uses RDB snapshots every 60
seconds and disables AOF. After an abrupt Redis loss, its last successful
snapshot may not contain recent admissions; restoring it can roll back the
counter. With that persistence setup this is not a hard ceiling across a Redis
restart. Do not describe or configure the app-side budget as a guaranteed
provider limit.

## Priorities and saturation

| Priority | Examples | At the noncritical limit |
| --- | --- | --- |
| Critical | OTP and password recovery | Uses reserved capacity; denied at the configured hard cap. |
| High | Password-change notices, bookings, cancellations, reschedules, waitlist offers, store alerts | Deferred in the outbox where available. |
| Medium | Appointment reminders | Deferred in the outbox until the next quota window. |
| Low | Rebook invitations | Dropped and recorded. |

The noncritical limit is the total cap minus the critical reserve. Redis Lua
scripts reserve each logical message atomically across API and Celery workers.
Repeated outbox or Celery delivery IDs do not consume another slot within the
same quota window. If a retry crosses the provider reset, the same logical
message can be admitted once in the new window and consume that window's slot.
SMTP sends are not retried after an ambiguous result because the provider may
already have accepted the message. An outbox send may retry a transient
failure positively identified before the message body starts, with the same
logical ID and budget admission within that quota window, up to 10 SMTP
attempts total. Delays are 20, 40, 80, and 160 seconds, then capped at 5
minutes. After the tenth failed attempt the row is closed as `failed`, with
its error recorded and one alert subject to the current alert limits. This is
a provisional owner policy (D-20261117-03): a valid reminder can be lost
during a prolonged SMTP outage. A refusal of the DATA command before the server's 354 response is
still pre-body; any uncertain result after body transmission is terminal and
marked `unknown`. The `failed` metric counts SMTP attempts, so a pre-body
attempt later delivered successfully can appear in both `failed` and `sent`
while consuming one `admitted` slot in that window. Redis reservation checks
use at most two attempts. If Redis is unavailable, outbox rows defer for 60
seconds without consuming an SMTP attempt; direct mail paths fail closed when
a cap is configured. With no cap configured, mail remains uncapped and a
Redis outage only loses budget metrics.

There is no exactly-once delivery guarantee. `admitted` means Shifty reserved
an internal slot; `sent` means the SMTP call returned success, not that the
recipient's inbox accepted or displayed the message. Provider acceptance can
be ambiguous after body transmission. The outbox commits each claim before
SMTP. A claim older than 120 seconds after worker loss becomes `unknown` and
is never resent, avoiding duplication of a message the provider may have
accepted. Pending schedules and timed retries survive scheduler or broker
restarts; delivery after an in-flight claim is still best-effort. Repeating an
idempotent admission does not prove delivery.

Outbox-backed high and medium messages stay pending when budget admission is
deferred or Redis is unavailable. A budget denial schedules the row for the
configured provider reset; Redis unavailability schedules it 60 seconds
later. Neither counts as an SMTP attempt, and the dispatcher continues to
other eligible rows. A reminder's appointment stage marker and its
`email.send` row commit in one SQL transaction. Before SMTP, the dispatcher
checks that the appointment still belongs to the outbox store, remains in an
open status, and has the same future start time captured by the reminder. A
cancelled, rescheduled, missing, or expired appointment makes the row
terminal `expired`. A pending row stays in SQL if the dispatcher or Celery
broker is unavailable, and a later outbox tick can resume it. Low-priority
rebook invitations are intentionally discarded at saturation. OTP uses a
Celery task without automatic retry;
password reset and password-change emails use request background tasks. Public
booking registration/confirmation emails use a separate Celery task with no
retry; budget denials return a failure result and the task finishes. Re-offers
from `waitlist.tasks` now commit the `OFFERED` state, expiry, and `email.send`
row together. The normal outbox dispatcher sends after commit and retries only
failures positively identified before message-body transmission, up to 10
SMTP attempts total. Ambiguous results after body transmission remain
terminal as `unknown`. Waitlist `OFFERED` state,
offer expiry, and its `email.send` row are still committed together. Offer
expiry starts when the offer is created, so a long dispatch delay can reduce
the customer's remaining time to accept it.

OTP, password reset/change, and public booking registration/confirmation still
use direct delivery paths without durable outbox retries. This PR does not
promise that those messages will be deferred or recovered after a process or
broker failure.

If Redis is unavailable with a cap configured, OTP and password reset fail
closed; users can request another OTP or reset email, but password-change
notices and public booking emails have no automatic retry. Critical messages
also stop at the configured hard cap. This differs from the inherited issue
wording that said OTP and password reset would continue above budget; this
implementation preserves the configured cap and does not promise delivery
after it is reached.

Redis stores current-window counters for `admitted`, `sent`, `failed`,
`deferred`, and `dropped`, plus admitted counts by priority. `deferred` counts
unique logical messages deferred in that window; a message later admitted in
the same window can appear in both counters. The internal reader is
`core.mail_budget.read_mail_budget_metrics()`.

## Authentication delivery boundary

The OTP task currently receives `to`, `subject`, and `body` as Celery
arguments; the OTP code is in the body serialized to the RabbitMQ broker.
The repository sets late acknowledgements and rejects tasks when a worker is
lost, but does not set an OTP task expiry or queue TTL. The actual RabbitMQ
retention policy cannot be confirmed from this repository. This is a
preexisting sensitive-payload exposure, not a security guarantee approved by
this budget change. The PR does not add OTP or password-reset material to the
SQL outbox; do not add durable auth delivery or retries until a separate
security design validates storage, access, expiry, and redelivery behavior.

Password-reset email is currently scheduled with web-process background tasks
after the token hash is committed. The raw reset URL is not sent through the
Celery broker or written to the outbox, but a process failure can lose the
email. Password-change notices and public booking emails also remain outside
the durable SQL outbox in this PR.
