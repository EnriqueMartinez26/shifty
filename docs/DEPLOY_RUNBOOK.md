# Deploy Runbook (Shifty)

How a release reaches the VPS, how it is rolled back, and what has to be true on the server before the first deploy. Plan items F0-02, F0-03, F0-20, F0-21 (`plan-correccion-rendimiento.md`).

The short version:

```bash
# CI already published ghcr.io/enriquemartinez26/shifty-{backend,frontend,nginx}:<sha>
cd /opt/shifty && git pull
make deploy APP_VERSION=<sha>      # migrate, roll the backend, gate, auto-rollback
make rollback                      # back to .deploy/previous, never migrates
make deploy-edge                   # only when nginx's image or nginx/nginx.prod.conf changed
```

## 1. One-time server setup

| Prerequisite | How to check |
| --- | --- |
| Docker Compose >= 2.24 (`ports: !reset []` in `docker-compose.prod.yml`) | `docker compose version` |
| Server `.env` sets `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` and `COMPOSE_PROJECT_NAME=shifty` | `docker compose config --services` lists the prod services without `-f` |
| Server `.env` does **not** set `APP_VERSION`. `docker-compose.prod.yml` requires it for every compose command (`${APP_VERSION:?}`); the deploy passes it and records it in `.deploy/current`, and the host scripts (backup, latency) read it from there. A value pinned in `.env` goes stale after the first deploy, and a bare `docker compose up -d` would bring that old version back | `grep -c APP_VERSION .env` is 0 |
| The deploy user is in the `docker` group (the scripts never use `sudo`) | `docker ps` as that user |
| `docker login ghcr.io` with a token that has `read:packages` (the packages are private) | `docker pull ghcr.io/enriquemartinez26/shifty-backend:latest` |
| `/etc/shifty/ops.env` from `deploy/ops.env.example` (`DOMAIN`, `BACKUP_REMOTE`, alerts) | `sudo cat /etc/shifty/ops.env` |
| Daily backup timer enabled, rclone remote and bucket (`docs/BACKUP_RESTORE_RUNBOOK.md`) | `systemctl list-timers shifty-backup.timer`, `cat /var/backups/shifty/last-success` |
| Host cron installed: `deploy/cron/shifty-guard`, `deploy/cron/shifty-latency`, `deploy/cron/shifty-pg-top`, `deploy/logrotate/shifty` | `ls /etc/cron.d/shifty-*` |
| certbot on the host with webroot `/opt/shifty/nginx/acme` (compose mounts `./nginx/acme` at `/var/www/acme` in nginx) and `scripts/cert-deploy-hook.sh` as deploy hook | `certbot renew --dry-run` |
| After adding the `pg_backups` volume to `docker-compose.prod.yml`, the `db` container was recreated once so the volume attaches (see below) | `docker compose exec db ls /backups` |
| python3 on the host (the latency report is stdlib only) | `python3 --version` |

certbot:

```bash
install -d /opt/shifty/nginx/acme /opt/shifty/nginx/certs
certbot certonly --webroot -w /opt/shifty/nginx/acme -d <domain> \
  --deploy-hook /opt/shifty/scripts/cert-deploy-hook.sh
```

The webroot is the HOST path of the bind mount: compose mounts `./nginx/acme` read-only at `/var/www/acme`, where `nginx/nginx.prod.conf` serves `/.well-known/acme-challenge/`. The certificates are **copied**, not symlinked, into `nginx/certs` (mounted at `/etc/nginx/certs`): a symlink to `/etc/letsencrypt/live/...` would point, inside the container, to a path that does not exist. `scripts/cert-deploy-hook.sh` does the copy (`$RENEWED_LINEAGE`) and then runs, in effect, `cd /opt/shifty && APP_VERSION=$(cat .deploy/current) docker compose exec -T nginx nginx -t && ... nginx -s reload` (the prod compose file needs `APP_VERSION` for every command). The first time, run the hook by hand with `RENEWED_LINEAGE=/etc/letsencrypt/live/<domain>` so `nginx/certs` exists before nginx starts with TLS. No OCSP stapling: Let's Encrypt turned it off.

`pg_backups` volume, once: the `db` service only gets the new `/backups` mount when its container is recreated, and `make deploy` never recreates `db`. In a maintenance window (Postgres restarts, a few seconds of 503):

```bash
cd /opt/shifty
APP_VERSION=$(cat .deploy/current) docker compose up -d --no-deps --no-build db
APP_VERSION=$(cat .deploy/current) docker compose exec db ls -ld /backups
```

Before the first deploy with this script there is no `.deploy/current`; use the sha that is about to be deployed.

The clone is assumed at `/opt/shifty` in the systemd unit and the cron files; edit those paths if it lives elsewhere. `SHIFTY_DIR` defaults to the clone the script belongs to, so do not set it in a shared `ops.env`.

## 2. Images (CI)

`.github/workflows/build-images.yml` runs on every push to `main` (and by hand). It builds `backend`, `frontend` and `nginx` and pushes `ghcr.io/enriquemartinez26/shifty-<service>:<git sha>` plus `:latest`. The backend image serves the API, the workers and beat. The VPS never builds: every `up` and `run` in `scripts/deploy.sh` carries `--no-build` (and every `up` `--remove-orphans`, so a renamed service does not leave its old container behind), and after the pull the script checks with `docker image inspect` that every `image:tag` of `docker compose config --images` is present. The `retention` job deletes untagged versions and keeps the 5 newest per package; it never fails the build.

`docker-compose.prod.yml` references `ghcr.io/enriquemartinez26/shifty-<service>:${APP_VERSION}` for backend (API, workers and beat) and frontend. The production edge runs the base image `nginx:1.27.5-alpine` with `nginx/nginx.prod.conf` bind-mounted, so its image does not change per release; the `shifty-nginx` image CI publishes is not what production runs.

## 3. Deploy sequence (`scripts/deploy.sh deploy`)

1. **Lock** `.deploy/lock` (a second deploy stops; the guard does not restart containers while it exists).
2. **Preflight**, before touching anything:
   - `COMPOSE_FILE` (from the environment or the clone's `.env`) includes `docker-compose.prod.yml`. The script `cd`s into the clone first, so it can be called from anywhere.
   - `BACKUP_DIR` exists (created with mode 0700 if missing: the `pg_backups` volume is a bind and does not create it).
   - Compose >= 2.24 and `docker compose config -q` passes.
   - Every service in `DEPLOY_SERVICES` exists (default: `backend celery_worker celery_worker_interactive celery_beat frontend`; nginx is not in the list).
   - The `db` service is running (the deploy uses `--no-deps` and never starts or recreates db, redis or rabbitmq).
   - Disk under 80 %.
   - `/var/backups/shifty/last-success` is younger than 24 h (`DEPLOY_SKIP_BACKUP_CHECK=1` only on staging).
3. Save the running version to `.deploy/previous` (from `.deploy/current`, or the tag of the running backend image on the first run).
4. `docker compose pull` of the app services, then `docker image inspect` of every expected `image:tag`. A failed pull or a missing image stops the deploy here, before migrating.
5. **Migrate before recreating**, with the old code still serving: `docker compose run --rm --no-deps --no-build -T backend alembic upgrade head`. If it fails, nothing was recreated.
6. **Backend, gradually**: `up -d --no-deps --no-build --remove-orphans --no-recreate --wait --scale backend=<old + 3> backend` starts 3 new replicas next to the old ones and waits until they are healthy. nginx resolves `backend` by itself (`server backend:8000 resolve`, `resolver 127.0.0.11 valid=5s`), so after `DEPLOY_DNS_SETTLE` (6 s) the old replicas are stopped (`docker stop -t 35`, graceful) and removed. If the new replicas do not become healthy within 180 s they are removed and the old ones keep serving: the deploy fails without a rollback because nothing else changed. Verified with Compose v5.5: `--no-recreate --scale` creates the missing replicas with the new configuration and leaves the existing ones alone. Requires the backend service without `container_name` (F0-04, `docker-compose.yml`). `DEPLOY_ROLLING=0` falls back to a plain `up -d --no-deps backend`, with about 5-10 s of 502 while the replicas are recreated.
7. The rest of the app: `up -d --no-deps --no-build --remove-orphans celery_worker celery_worker_interactive celery_beat frontend`. Compose only recreates what changed. The frontend container is recreated when its image changes (every release): the SPA answers 502 for a moment while it restarts. Accepted: the API keeps serving and the browser retries.
8. `nginx -t && nginx -s reload`. On a normal deploy the edge is only **reloaded**, never recreated or restarted; it re-resolves `backend` by itself.
9. Write `.deploy/current`.
10. **Gate** (60 s: 12 checks, 5 s apart):
    - `https://$DOMAIN/api/ops/health/ready` and `https://$DOMAIN/` answer 2xx; one failed check in total is tolerated.
    - No container of the project is `unhealthy`.
    - `rabbitmq-diagnostics alarms` is empty (with a memory or disk alarm RabbitMQ blocks publishers: OTP and jobs stall while `/ready` still answers).
    - 5xx rate in the last 2 minutes of the nginx access log (`"s":"5..."`) under 0.5 %, counted only when there are at least 3 errors (one stray 502 on low traffic does not trigger a rollback).
11. Gate failed: **automatic rollback** (`DEPLOY_AUTO_ROLLBACK=1`), then exit 1. If the rollback's own gate also fails, the script alerts and exits 2: a person has to look.

Every step logs to stderr with a UTC timestamp. Failures send an alert through `ALERT_EMAIL`/`ALERT_WEBHOOK_URL`.

## 4. Rollback (`scripts/deploy.sh rollback`)

`APP_VERSION=$(cat .deploy/previous)`, then steps 4 and 6-10 **without migrating**. It does not rewrite `.deploy/previous`, so running it twice does not bounce between versions. Preflight skips the disk and backup checks: it is the emergency path.

If the pull fails (GHCR down, token expired), the rollback continues with the local images, but only if every previous `image:tag` is still on the host. If one is missing it alerts and exits 2 without touching anything: there is nothing to roll back to, and a person decides.

## 4b. The edge (`make deploy-edge`)

nginx is recreated only by `scripts/deploy.sh edge`, and only when something changed: the id of its image (after `pull nginx`) differs from the running container's, or the sha256 of `nginx/nginx.prod.conf` differs from the one recorded in `.deploy/edge-conf.sha256` on the last run. A conf change needs a recreate, not just a reload: the conf is a single-file bind mount, and when `git pull` replaces the file the container keeps seeing the old inode. Recreating the edge drops every connection for a moment; do it outside peak hours. With nothing changed it only runs `nginx -t && nginx -s reload`.

Rollback is safe only because of the migration rule below: the previous release must work against the schema the new one migrated to.

Rolling back **below** the release that ships `e7a9c1d3f5b8` (service images uploaded to `store_media`, plan F1-28): the images keep being served by id and `services.image_url` stores an absolute `https` URL, which the previous release accepts. Only if that release cannot serve them (the media route changed) clear the links first, with the migration role:

```sql
UPDATE services SET image_url = NULL WHERE image_url LIKE '%/stores/media/%';
```

The rows stay in `store_media` (the downgrade never deletes images). A later upgrade links each one back to the service whose `image_url` still ends in `/stores/media/{id}`; if the links were cleared with the `UPDATE` above, those images have no service left and the upgrade stops with their count. Deleting them is a human decision: `DELETE FROM store_media WHERE kind = 'service' AND id NOT IN (SELECT substring(image_url FROM '/stores/media/([A-Za-z0-9_-]+)$') FROM services WHERE image_url IS NOT NULL);`

## 5. Migrations: expand/contract

- A release only **adds** (expand): new nullable columns, new tables, new indexes. Code that stops using a column ships first; the migration that drops it (contract) ships in a **later** release.
- Indexes on live tables: `CREATE INDEX CONCURRENTLY` inside `op.get_context().autocommit_block()`, preceded by `DROP INDEX CONCURRENTLY IF EXISTS` (a failed concurrent build leaves an invalid index behind).
- Constraints: `NOT VALID` first, `VALIDATE CONSTRAINT` in a separate step.
- Backfills in batches, never one `UPDATE` over the whole table; no `ALTER TYPE` that rewrites a table.
- `lock_timeout` for the migration role (`alembic/env.py`, plan F0-06): a migration that waits for a lock fails fast instead of queueing every request behind it.
- `MERCADOPAGO_LINK_REF_ENABLED` (default `true`) makes every new payment link carry `<appointment>:<link_ref>` as its Mercado Pago `external_reference` (migration `f1b3d5e7a9c2` adds `payments.link_ref`). Payment-link integrity requires the reference of the charge's CURRENT link, so a late payment on a replaced link is never applied to the new one. Every link a charge stops using (regenerated or repriced) is recorded in `payment_link_history` (migration `a3c5e7f9b1d2`, a new table: expand only). An `approved` payment on a recorded link, for that link's amount and currency, is adopted by a charge that is not accredited yet (the charge takes that link and its current link is sent to expire); any other payment on a replaced link alerts the owner and Sentry once per Mercado Pago payment. Shifty has never run in production, so no link without a nonce can be in flight at the first deploy. With the flag off, links already issued with a nonce keep matching, new links use the bare appointment id, and regenerating the link of an `expired` payment is refused with 409 `PAYMENT_LINK_REGENERATION_UNAVAILABLE`, so the double-payment window never opens.
- **Rolling back to code older than this release** (the one that ships `f1b3d5e7a9c2`): that code does not understand the nonce and rejects every payment on a link already issued with one. Switch the flag off at least one link lifetime BEFORE the rollback:
  1. Set `MERCADOPAGO_LINK_REF_ENABLED=false` in the server `.env` (production hands the whole `.env` to the app services) and recreate them on the running version: `APP_VERSION=$(cat .deploy/current) docker compose up -d --no-deps --no-build backend celery_worker celery_worker_interactive celery_beat`. Do not use `make deploy` with the running sha for this: it overwrites `.deploy/previous` with the running version, and `make rollback` would then target the release you are leaving.
  2. Wait until no live charge carries a nonce link. A link expires with its hold (`PAYMENT_HOLD_MINUTES`) or, for a panel link, at the appointment start, so the wait can be days. With the migration role, this must return 0: `SELECT count(*) FROM payments p JOIN appointments a ON a.id = p.appointment_id WHERE p.link_ref IS NOT NULL AND p.status IN ('pending', 'rejected') AND COALESCE(a.expires_at, a.starts_at) > now();` Also wait until no `payment.preference.expire` is pending (a replaced link is only dead once Mercado Pago expired it); this must return 0 too: `SELECT count(*) FROM outbox_messages WHERE event_type = 'payment.preference.expire' AND (processed_at IS NULL OR error = 'claimed:payment.preference.expire');` An expire that exhausted its attempts is `processed_at` set with a real error (not the claim marker): Mercado Pago never expired that link and it may still be payable. List them and expire each one by hand BEFORE the rollback (with the store's token: `PUT /checkout/preferences/{preference_id}` with `"expires": true` and `"expiration_date_to"` = now, the same call the job makes): `SELECT id, store_id, payload->>'preference_id' AS preference_id, attempts, error, processed_at FROM outbox_messages WHERE event_type = 'payment.preference.expire' AND processed_at IS NOT NULL AND error IS NOT NULL AND error <> 'claimed:payment.preference.expire' ORDER BY processed_at DESC;`
  3. `make rollback`. It needs no migration: the older code ignores `payments.link_ref`, `payments.reconciled_at` (both added by `f1b3d5e7a9c2`; `reconciled_at` only orders the reconciliation queue, so leaving it is harmless) and `payment_link_history`.
  - **After the rollback, refunds and chargebacks of charges already paid through a nonce link go to dead letter.** Their Mercado Pago payment carries `<appointment>:<link_ref>` as its reference, the older code requires the bare appointment id, and the inbox gives up after 10 attempts: the charge stays `approved` in Shifty although the money went back. The older code has no `dead_letter_webhooks` metric in `/ops/slo`; look for them directly with the migration role: `SELECT id, store_id, event_id, attempts, error, processed_at FROM webhook_inbox WHERE processed_at IS NOT NULL AND error IS NOT NULL AND processed_at > now() - interval '24 hours' ORDER BY processed_at DESC;` Repeat this query every day until the next release is deployed: nothing alerts on these on the older code. Before the rollback, list those charges with the migration role and watch them in Mercado Pago until the next release is back: `SELECT p.store_id, p.appointment_id, p.id AS payment_id, p.external_payment_id, p.amount, p.paid_at FROM payments p WHERE p.link_ref IS NOT NULL AND p.status = 'approved' ORDER BY p.paid_at DESC;` A refund or chargeback found there is registered by hand from the panel (`POST /payments/{payment_id}/refund` with `manual: true`).

## 5b. Pre-deploy data checks

Some migrations add a constraint that the application code already respected, and first count the rows that would violate it. If a count is not zero the migration **stops with the count** and changes nothing: it does not normalize, trim or delete data for anyone. Run these on production (read-only) before the deploy that ships them; every one must return 0.

```sql
-- c4e6a8b0d2f1: emails with uppercase letters (ck_users_email_lower).
-- Two rows may collapse into the same identity: decide by hand.
SELECT count(*) FROM users WHERE email <> lower(email);

-- e9f1b3d5a7c0: appointments longer than one day (ck_appointments_max_span).
SELECT count(*) FROM appointments WHERE ends_at > starts_at + interval '1 day';

-- c3d5e7f9a1b4: services longer than 1440 minutes (ck_services_duration_max).
SELECT count(*) FROM services WHERE duration_minutes > 1440;

-- c3d5e7f9a1b4: blocks and appointments whose store is not their staff's store.
SELECT count(*) FROM appointment_blocks b JOIN staff s ON s.id = b.staff_id
WHERE b.store_id <> s.store_id;
SELECT count(*) FROM appointments a JOIN staff s ON s.id = a.staff_id
WHERE a.store_id <> s.store_id;

-- e7a9c1d3f5b8: uploaded images with an unknown kind (ck_store_media_kind).
SELECT count(*) FROM store_media WHERE kind NOT IN ('logo', 'cover', 'service');
```

Run them as the migration role (or any role that bypasses RLS): as `shifty_app` without a tenant context, RLS hides every row and the counts are a false 0.

## 6. Staging: a second compose project on the same VPS

Until launch (plan §7, decision 29) staging is another clone, for example `/opt/shifty-staging`, with its own `.env`:

- `COMPOSE_PROJECT_NAME=shifty-staging`: containers, networks and volumes (the database included) are separate from production. Container names are `${COMPOSE_PROJECT_NAME:-shifty}_<service>` in the compose files, so the two projects do not collide (a fixed `container_name` would stop the second project from starting). The guard watches only its own project (`COMPOSE_PROJECT_NAME`).
- Its own secrets, `DOMAIN` and `BACKUP_DIR=/var/backups/shifty-staging` with `BACKUP_ALLOW_LOCAL_ONLY=1`, in its own ops file; point its scripts at it with `SHIFTY_OPS_ENV=/etc/shifty/ops-staging.env`.
- Production nginx publishes 80 and 443, so staging nginx needs other host ports (for example `127.0.0.1:8443:443`) through an extra override listed in its `COMPOSE_FILE`. That override does not exist yet.
- Deploy it with the same script: `APP_VERSION=<sha> DEPLOY_SKIP_BACKUP_CHECK=1 bash scripts/deploy.sh deploy` from its clone.
- It shares 16 GB with production: bring it up for a test and take it down afterwards (`docker compose down`, the volumes stay).

The monthly backup drill can restore into staging (`docs/BACKUP_RESTORE_RUNBOOK.md`).

### Acceptance test against staging

Run Locust from **another machine** (plan §9). The edge limits requests per client IP: `/api/` 20 r/s (burst 40), `/api/auth/` 3 r/s (burst 6), 40 connections per IP, all answered as `429 RATE_LIMITED`. A single load generator hits those limits long before the app does, so use several source IPs or raise the limits temporarily in the staging nginx config, and write down which one was used next to the results. The full procedure, pass criteria and the check script are in `docs/PERF_ACCEPTANCE.md`.

## 7. What the edge answers by itself

nginx returns canonical JSON for its own errors under `/api`: `502/503/504` as `UPSTREAM_UNAVAILABLE` with `Retry-After: 5`, `413` as `REQUEST_TOO_LARGE`, and `429` as `RATE_LIMITED`. During a plain (non-gradual) backend recreate, clients see `UPSTREAM_UNAVAILABLE` and retry.

The edge also caches, and only what the backend marks cacheable (plan F1-29): `/api/stores/media/{id}` (immutable, one year) and `/api/public/services` and `/api/public/staff` (`s-maxage=30`, `stale-while-revalidate=30`, so a catalog change can take up to 60 s to show). Requests with `Authorization` or `Origin` bypass it. The cache lives in the container (`/var/cache/nginx/shifty`, 512 MB max) and starts empty after every edge recreate. To drop it by hand, recreate the edge.

`X-Request-ID` belongs to Mercado Pago's webhook signature and is never overwritten; the edge's own id goes to the backend as `X-Edge-Request-Id` and appears as `rid` in the access log.

## 8. Host operations that run on their own

| What | When | Script | Alerts when |
| --- | --- | --- | --- |
| Restart `unhealthy` containers | every minute (cron) | `scripts/guard.sh` | every restart. Never restarts `db` or `rabbitmq` (alert only), one-off containers (`compose run`) or anything while `db` or `redis_state` is unhealthy (the rest fails because of them). Caps: 3 restarts per container and 6 in total per hour |
| NTP, TLS certificate, disk, per-container memory, `docker stats` to `/var/log/shifty/stats.log` | hourly (cron) | `scripts/checks.sh` | NTP not synchronized, certificate < 20 days, disk > 80 % (critical > 90 %), container > 90 % of its memory limit |
| Backup freshness | hourly (cron) | `scripts/backup-check.sh` | last successful backup > 26 h (critical > 48 h) |
| Latency and 5xx per route | every 5 min (cron) | `scripts/latency-check.sh` + `backend/scripts/latency_report.py` | a route with >= 20 requests over p95 500 ms or 5xx 0.1 %, or global 5xx over 0.1 % with >= 200 requests in the window |
| Top 20 queries of `pg_stat_statements` | Mondays 06:23 host time (cron; cron.d uses the host timezone) | `backend/scripts/pg_top_queries.py` inside the backend container | never: it is a report, read `/var/log/shifty/pg-top.log` |
| Daily backup | 03:00 ART (systemd timer) | `scripts/backup.sh` | any failure, or no `BACKUP_REMOTE` |
| Certificate renewal | certbot's own timer | `scripts/cert-deploy-hook.sh` | nginx did not reload after a renewal |

Repeated alerts are silenced for a while (30 minutes to 6 hours depending on the check) so a condition that lasts does not send a mail every minute. The guard does nothing while `.deploy/lock` exists.

**Weekly query report (plan F5-03).** `deploy/cron/shifty-pg-top` runs `docker compose exec -T backend python scripts/pg_top_queries.py` every Monday and appends to `/var/log/shifty/pg-top.log`: the 20 statements with the most total time and the 20 with the highest mean time, with calls, rows and their share of the total. It connects as the owner role (`BACKUP_DATABASE_URL` or `MIGRATION_DATABASE_URL`, never `DATABASE_URL`: under `shifty_app` the view hides other roles' query text) and prints the URL with the credentials masked; the query text is normalized by Postgres (`$1` instead of values), so it carries no customer data. Totals accumulate since the last reset, so compare week against week; to measure a single week run it by hand with `--reset` (it clears the stats after printing). By hand: `APP_VERSION=$(cat .deploy/current) docker compose exec -T backend python scripts/pg_top_queries.py --limit 20`.

**Sentry (plan F5-02).** With `SENTRY_DSN` set, traces are sampled per route (`backend/core/observability.py`): never `/ops/health/*` or `/ops/slo`, always `/payments/*` and the Mercado Pago webhook, 2 % of public GETs, 20 % of writes, 10 % of other panel reads; the release is `APP_VERSION`. Sentry Crons watches the beat tasks: the 8 crontab tasks become 8 cron monitors, which count against the Sentry plan's cron quota (owner decision; `exclude_beat_tasks` in the `CeleryIntegration` drops the ones not worth a monitor). The outbox task runs every 20 s and Sentry skips intervals under 60 s, so it has no monitor: its lag is covered by `/ops/slo` (`oldest_pending_outbox_seconds`, `oldest_pending_email_send_seconds`).

Logs: the scripts write to `/var/log/shifty/*.log` (14 days, `deploy/logrotate/shifty`). The nginx error log still prints the full request line, query string included (it can carry `client_phone`), on 429 and upstream errors: keep it only in the container's json-file log with the size cap of the compose logging settings (plan F0-22: json-file 20 MB x 5) and do not copy it anywhere else. `latency-check.sh` reads the access log into a temporary file and deletes it.

## 8b. Data retention (Celery beat, not cron)

`purge_expired_data` runs daily at 04:30 UTC (`core/celery_app.py`; code in `backend/modules/housekeeping/retention.py`). The owner decided the windows (plan F1-19, decision 17; the dead-letter window was decided by the coordinator under the owner's delegation). Each one is a setting with a floor of 1 day, so a typo cannot turn into "delete everything":

| Table | Deleted when | Setting (default) | Never deleted |
| --- | --- | --- | --- |
| `outbox_messages` | processed without error more than 90 days ago | `RETENTION_OUTBOX_PROCESSED_DAYS` (90) | pending rows (`processed_at` NULL) and in-flight Mercado Pago link-expiry claims |
| `webhook_inbox` | processed without error more than 90 days ago | `RETENTION_INBOX_PROCESSED_DAYS` (90) | pending rows |
| `outbox_messages` / `webhook_inbox` dead letters (`error` set, never applied: attempts exhausted, mail not sent) | processed more than 365 days ago | `RETENTION_DEAD_LETTER_DAYS` (365) | same as above; kept a year as evidence for payment disputes |
| `otp_verifications` | expired more than 7 days ago | `RETENTION_OTP_EXPIRED_DAYS` (7) | codes still valid or expired less than 7 days ago |
| `notifications` | read more than 180 days ago | `RETENTION_NOTIFICATIONS_READ_DAYS` (180) | unread notifications |
| `audit_logs` | never | — | everything: it is evidence, archive it outside the database |

It deletes in batches of `RETENTION_BATCH_SIZE` (5000) with a commit per batch. Only one run goes at a time (session advisory lock), and each run has a 90 s budget: whatever does not fit is picked up the next day. `auth_sessions` keeps its own job (`purge_expired_auth_sessions`, 04:00 UTC, 30 days).

- **Dry run first**: set `RETENTION_DRY_RUN=true` for the first days after the first deploy; the task then only counts and logs `purge_expired_data_done`. One manual dry run: `APP_VERSION=$(cat .deploy/current) docker compose exec celery_worker celery -A core.celery_app call purge_expired_data --kwargs '{"dry_run": true}'`.
- **Restores**: a backup restored today brings back rows that the next 04:30 run deletes again. That is expected.
- **Indexes**: the purge reads `ix_outbox_processed_history`, `ix_webhook_inbox_processed_history` and `ix_notifications_read_history` (partial, history rows only; migration `e5f7a9b1c3d6`). `otp_verifications` uses its `expires_at` index.

## 9. Troubleshooting

- **"hay otro deploy en curso"**: another deploy is running, or one was killed. If none is running, `rmdir .deploy/lock`.
- **"COMPOSE_FILE ... no incluye docker-compose.prod.yml"**: the server `.env` lacks `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`.
- **"faltan imagenes locales"**: the sha was not published (check the `Build images` run for that commit) or `docker login ghcr.io` expired.
- **Manual compose commands** need the version (the prod compose file refuses to interpolate without it): `APP_VERSION=$(cat .deploy/current) docker compose ps`.
- **First deploy with this script**: `.deploy/previous` comes from the tag of the running backend image. If that is `latest` or a local build, there is nothing to roll back to; say so in the release notes.
- **The gate failed but the release is fine** (for example the domain's DNS or certificate): fix the cause and deploy the same sha again; migrations are idempotent at head.
