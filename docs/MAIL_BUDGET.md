# SMTP daily budget

Shifty applies an optional best-effort budget at the shared SMTP sink. This
does not guarantee the provider's account quota: it counts sends made through
Shifty, while other apps or manual sends using the same account are outside
the counter. The application does not assume a provider plan or a fixed cap:
`MAIL_DAILY_BUDGET` is unset by default. Before setting it, verify the
configured account's current quota, reset time, and timezone in provider
documentation or account settings.

## Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `MAIL_DAILY_BUDGET` | unset | Maximum admitted messages in one provider calendar window. Must be a positive integer when set. |
| `MAIL_BUDGET_ALERT_PERCENT` | `80` | Emit one Sentry warning when admitted messages first reach this percentage. |
| `MAIL_CRITICAL_RESERVE_PERCENT` | `20` | Keep this fraction of the cap available to critical messages. |
| `MAIL_BUDGET_TIMEZONE` | `UTC` | IANA timezone used for the provider's calendar reset. |
| `MAIL_BUDGET_RESET_HOUR` | `0` | Local hour, 0–23, when the provider quota window resets. |

The cap, timezone, and reset hour must match the provider's actual quota
window. The control only covers messages sent by Shifty processes that share
the same non-evicting Redis instance. An incorrect window or sends from outside
Shifty can still exceed the provider's quota.

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
Repeated outbox or Celery delivery IDs do not consume another slot. SMTP sends
are not retried after an ambiguous result because the provider may already have
accepted the message. An outbox send may retry a transient failure positively
identified before DATA on a later tick, with the same logical ID, one budget
admission, and the existing bounded outbox attempt limit. Once DATA starts,
4xx responses, timeouts, and disconnects remain terminal. The `failed` metric
counts SMTP attempts, so a pre-DATA attempt later delivered successfully can
appear in both `failed` and `sent` while consuming one `admitted` slot. Redis
reservation checks use at most two attempts; when a cap is configured and
Redis remains unavailable, mail admission fails closed. With no cap configured,
mail remains uncapped and a Redis outage only loses budget metrics.

Outbox-backed high and medium messages stay pending when budget admission is
deferred or Redis is unavailable; reminders release their durable claim and
retry on a later tick. Low-priority rebook invitations are intentionally
discarded at saturation. OTP uses a Celery task without automatic retry;
password reset and password-change emails use request background tasks. Public
booking registration/confirmation emails use a separate Celery task with no
retry; budget denials return a failure result and the task finishes. Re-offers
from `waitlist.tasks` now commit the `OFFERED` state, expiry, and `email.send`
row together. The normal outbox dispatcher sends after commit and retries only
failures positively identified before SMTP DATA, within the existing attempt
limit. Ambiguous results after DATA remain terminal. Offer expiry starts when
the offer is created, so a long dispatch delay can reduce the customer's
remaining time to accept it.

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
