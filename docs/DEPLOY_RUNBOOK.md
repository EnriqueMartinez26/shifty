# Deploy Runbook (Shifty)

How a release reaches the VPS, how it is rolled back, and what has to be true on the server before the first deploy. Plan items F0-02, F0-03, F0-20, F0-21 (`plan-correccion-rendimiento.md`).

The short version:

```bash
# CI already published ghcr.io/enriquemartinez26/shifty-{backend,frontend,nginx}:<sha>
cd /opt/shifty && git pull
make deploy APP_VERSION=<sha>      # migrate, roll the backend, gate, auto-rollback
make rollback                      # back to .deploy/previous, never migrates
```

## 1. One-time server setup

| Prerequisite | How to check |
| --- | --- |
| Docker Compose >= 2.24 (`ports: !reset []` in `docker-compose.prod.yml`) | `docker compose version` |
| Server `.env` sets `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` and `COMPOSE_PROJECT_NAME=shifty` | `docker compose config --services` lists the prod services without `-f` |
| Server `.env` does **not** set `APP_VERSION` (the deploy passes it; a bare `docker compose up` must fail instead of silently running another version) | `grep -c APP_VERSION .env` is 0 |
| The deploy user is in the `docker` group (the scripts never use `sudo`) | `docker ps` as that user |
| `docker login ghcr.io` with a token that has `read:packages` (the packages are private) | `docker pull ghcr.io/enriquemartinez26/shifty-backend:latest` |
| `/etc/shifty/ops.env` from `deploy/ops.env.example` (`DOMAIN`, `BACKUP_REMOTE`, alerts) | `sudo cat /etc/shifty/ops.env` |
| Daily backup timer enabled, rclone remote and bucket (`docs/BACKUP_RESTORE_RUNBOOK.md`) | `systemctl list-timers shifty-backup.timer`, `cat /var/backups/shifty/last-success` |
| Host cron installed: `deploy/cron/shifty-guard`, `deploy/cron/shifty-latency`, `deploy/logrotate/shifty` | `ls /etc/cron.d/shifty-*` |
| certbot on the host, webroot `/var/www/acme` mounted into the nginx container, renewal hook reloads nginx | `certbot renew --dry-run` |
| python3 on the host (the latency report is stdlib only) | `python3 --version` |

certbot: `certbot certonly --webroot -w /var/www/acme -d <domain> --deploy-hook "cd /opt/shifty && docker compose exec nginx nginx -s reload"`, and copy or link the certificates to where `docker-compose.prod.yml` mounts them (`./nginx/certs`). The `/var/www/acme` volume on nginx is part of the compose files (lane B). No OCSP stapling: Let's Encrypt turned it off.

The clone is assumed at `/opt/shifty` in the systemd unit and the cron files; edit those paths if it lives elsewhere. `SHIFTY_DIR` defaults to the clone the script belongs to, so do not set it in a shared `ops.env`.

## 2. Images (CI)

`.github/workflows/build-images.yml` runs on every push to `main` (and by hand). It builds `backend`, `frontend` and `nginx` and pushes `ghcr.io/enriquemartinez26/shifty-<service>:<git sha>` plus `:latest`. The backend image serves the API, the workers and beat. The VPS never builds: `APP_VERSION` is always a sha that CI published. The `retention` job deletes untagged versions and keeps the 5 newest per package; it never fails the build.

The compose files reference `image: ghcr.io/enriquemartinez26/shifty-<service>:${APP_VERSION}` (lane B, `docker-compose.prod.yml`).

## 3. Deploy sequence (`scripts/deploy.sh deploy`)

1. **Lock** `.deploy/lock` (a second deploy stops; the guard does not restart containers while it exists).
2. **Preflight**, before touching anything:
   - Compose >= 2.24 and `docker compose config -q` passes.
   - Every service in `DEPLOY_SERVICES` exists (default: `backend celery_worker celery_worker_interactive celery_beat frontend nginx`).
   - The `db` service is running (the deploy uses `--no-deps` and never starts or recreates db, redis or rabbitmq).
   - Disk under 80 %.
   - `/var/backups/shifty/last-success` is younger than 24 h (`DEPLOY_SKIP_BACKUP_CHECK=1` only on staging).
3. Save the running version to `.deploy/previous` (from `.deploy/current`, or the tag of the running backend image on the first run).
4. `docker compose pull` of the app services.
5. **Migrate before recreating**, with the old code still serving: `docker compose run --rm --no-deps -T backend alembic upgrade head`. If it fails, nothing was recreated.
6. **Backend, gradually**: `up -d --no-deps --no-recreate --wait --scale backend=<old + 3> backend` starts 3 new replicas next to the old ones and waits until they are healthy. nginx resolves `backend` by itself (`server backend:8000 resolve`, `resolver 127.0.0.11 valid=5s`), so after `DEPLOY_DNS_SETTLE` (6 s) the old replicas are stopped (`docker stop -t 35`, graceful) and removed. If the new replicas do not become healthy within 180 s they are removed and the old ones keep serving: the deploy fails without a rollback because nothing else changed. Verified with Compose v5.5: `--no-recreate --scale` creates the missing replicas with the new configuration and leaves the existing ones alone. Requires the backend service without `container_name` (lane B, F0-04). `DEPLOY_ROLLING=0` falls back to a plain `up -d --no-deps backend`, with about 5-10 s of 502 while the replicas are recreated.
7. The rest of the app: `up -d --no-deps celery_worker celery_worker_interactive celery_beat frontend nginx`. Compose only recreates what changed.
8. `nginx -t && nginx -s reload` (in case the nginx image or config changed; never `restart`).
9. Write `.deploy/current`.
10. **Gate** (60 s: 12 checks, 5 s apart):
    - `https://$DOMAIN/api/ops/health/ready` and `https://$DOMAIN/` answer 2xx; one failed check in total is tolerated.
    - No container of the project is `unhealthy`.
    - 5xx rate in the last 2 minutes of the nginx access log (`"s":"5..."`) under 0.5 %, counted only when there are at least 3 errors (one stray 502 on low traffic does not trigger a rollback).
11. Gate failed: **automatic rollback** (`DEPLOY_AUTO_ROLLBACK=1`), then exit 1. If the rollback's own gate also fails, the script alerts and exits 2: a person has to look.

Every step logs to stderr with a UTC timestamp. Failures send an alert through `ALERT_EMAIL`/`ALERT_WEBHOOK_URL`.

## 4. Rollback (`scripts/deploy.sh rollback`)

`APP_VERSION=$(cat .deploy/previous)`, then steps 4 and 6-10 **without migrating**. It does not rewrite `.deploy/previous`, so running it twice does not bounce between versions. Preflight skips the disk and backup checks: it is the emergency path.

Rollback is safe only because of the migration rule below: the previous release must work against the schema the new one migrated to.

## 5. Migrations: expand/contract

- A release only **adds** (expand): new nullable columns, new tables, new indexes. Code that stops using a column ships first; the migration that drops it (contract) ships in a **later** release.
- Indexes on live tables: `CREATE INDEX CONCURRENTLY` inside `op.get_context().autocommit_block()`, preceded by `DROP INDEX CONCURRENTLY IF EXISTS` (a failed concurrent build leaves an invalid index behind).
- Constraints: `NOT VALID` first, `VALIDATE CONSTRAINT` in a separate step.
- Backfills in batches, never one `UPDATE` over the whole table; no `ALTER TYPE` that rewrites a table.
- `lock_timeout` for the migration role (`alembic/env.py`, plan F0-06): a migration that waits for a lock fails fast instead of queueing every request behind it.

## 6. Staging: a second compose project on the same VPS

Until launch (plan §7, decision 29) staging is another clone, for example `/opt/shifty-staging`, with its own `.env`:

- `COMPOSE_PROJECT_NAME=shifty-staging`: containers, networks and volumes (the database included) are separate from production.
- Its own secrets, `DOMAIN` and `BACKUP_DIR=/var/backups/shifty-staging` with `BACKUP_ALLOW_LOCAL_ONLY=1`, in its own ops file; point its scripts at it with `SHIFTY_OPS_ENV=/etc/shifty/ops-staging.env`.
- Production nginx publishes 80 and 443, so staging nginx needs other host ports (for example `127.0.0.1:8443:443`) through an extra override listed in its `COMPOSE_FILE`. That override does not exist yet.
- Deploy it with the same script: `APP_VERSION=<sha> DEPLOY_SKIP_BACKUP_CHECK=1 bash scripts/deploy.sh deploy` from its clone.
- It shares 16 GB with production: bring it up for a test and take it down afterwards (`docker compose down`, the volumes stay).

The monthly backup drill can restore into staging (`docs/BACKUP_RESTORE_RUNBOOK.md`).

### Acceptance test against staging

Run Locust from **another machine** (plan §9). The edge limits requests per client IP: `/api/` 20 r/s (burst 40), `/api/auth/` 3 r/s (burst 6), 40 connections per IP, all answered as `429 RATE_LIMITED`. A single load generator hits those limits long before the app does, so use several source IPs or raise the limits temporarily in the staging nginx config, and write down which one was used next to the results.

## 7. What the edge answers by itself

nginx returns canonical JSON for its own errors under `/api`: `502/503/504` as `UPSTREAM_UNAVAILABLE` with `Retry-After: 5`, `413` as `REQUEST_TOO_LARGE`, and `429` as `RATE_LIMITED`. During a plain (non-gradual) backend recreate, clients see `UPSTREAM_UNAVAILABLE` and retry.

`X-Request-ID` belongs to Mercado Pago's webhook signature and is never overwritten; the edge's own id goes to the backend as `X-Edge-Request-Id` and appears as `rid` in the access log.

## 8. Host operations that run on their own

| What | When | Script | Alerts when |
| --- | --- | --- | --- |
| Restart `unhealthy` containers | every minute (cron) | `scripts/guard.sh` | every restart; after 3 restarts of the same container in 1 h it stops restarting it |
| NTP, TLS certificate, disk, per-container memory, `docker stats` to `/var/log/shifty/stats.log` | hourly (cron) | `scripts/checks.sh` | NTP not synchronized, certificate < 20 days, disk > 80 % (critical > 90 %), container > 90 % of its memory limit |
| Backup freshness | hourly (cron) | `scripts/backup-check.sh` | last successful backup > 26 h (critical > 48 h) |
| Latency and 5xx per route | every 5 min (cron) | `scripts/latency-check.sh` + `backend/scripts/latency_report.py` | a route with >= 20 requests over p95 500 ms or 5xx 0.1 %, or global 5xx over 0.1 % |
| Daily backup | 03:00 ART (systemd timer) | `scripts/backup.sh` | any failure, or no `BACKUP_REMOTE` |

Repeated alerts are silenced for a while (30 minutes to 6 hours depending on the check) so a condition that lasts does not send a mail every minute. The guard does nothing while `.deploy/lock` exists.

Logs: the scripts write to `/var/log/shifty/*.log` (14 days, `deploy/logrotate/shifty`). The nginx error log still prints the full request line, query string included (it can carry `client_phone`), on 429 and upstream errors: keep it only in the container's json-file log with the size cap of the compose `x-logging` anchor (lane B) and do not copy it anywhere else. `latency-check.sh` reads the access log into a temporary file and deletes it.

## 9. Troubleshooting

- **"hay otro deploy en curso"**: another deploy is running, or one was killed. If none is running, `rmdir .deploy/lock`.
- **Manual compose commands** need the version: `APP_VERSION=$(cat .deploy/current) docker compose ps`.
- **First deploy with this script**: `.deploy/previous` comes from the tag of the running backend image. If that is `latest` or a local build, there is nothing to roll back to; say so in the release notes.
- **The gate failed but the release is fine** (for example the domain's DNS or certificate): fix the cause and deploy the same sha again; migrations are idempotent at head.
