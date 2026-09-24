# Release Checklist (Shifty)

Use this checklist for every production release. A release is ready only when each active item is checked or has an explicit owner-approved exception recorded in the release notes.

## 1. Configuration and secrets

- [ ] Production environment variables match `.env.production.example` and the deployment platform values.
- [ ] `DATABASE_URL`, `REDIS_URL`, JWT/auth secrets, payment provider secrets, Sentry DSN, SMTP/webhook secrets, and admin bootstrap credentials are present only in the secret manager.
- [ ] No production secret is committed, pasted in logs, or stored in local shell history.
- [ ] Secret rotation impact has been reviewed for long-lived workers and scheduled jobs.
- [ ] The server runs Docker Compose >= 2.24 (`docker compose version`), and `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` shows `ports` only on nginx. An older Compose may ignore `!reset []` and publish db, redis, rabbitmq and backend on the host again. `scripts/deploy.sh` refuses to run on an older Compose.
- [ ] The server `.env` sets `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` and `COMPOSE_PROJECT_NAME=shifty`, and does not set `APP_VERSION` (the deploy passes it). `/etc/shifty/ops.env` exists (from `deploy/ops.env.example`).

## 1b. Deploy prerequisites on the VPS (once, see `docs/DEPLOY_RUNBOOK.md` §1)

- [ ] The VPS is logged in to GHCR (`docker login ghcr.io`, token with `read:packages`) and the release sha was published by `.github/workflows/build-images.yml`.
- [ ] rclone is installed with a remote for the off-host bucket (created by the owner), and `BACKUP_REMOTE` is set in `/etc/shifty/ops.env`.
- [ ] `shifty-backup.timer` is enabled (`systemctl list-timers shifty-backup.timer`) and `/var/backups/shifty/last-success` is younger than 24 h.
- [ ] Host cron and logrotate are installed: `/etc/cron.d/shifty-guard`, `/etc/cron.d/shifty-latency`, `/etc/cron.d/shifty-pg-top`, `/etc/logrotate.d/shifty`.
- [ ] certbot is installed on the host with webroot `/opt/shifty/nginx/acme` (compose mounts it at `/var/www/acme` in nginx) and `--deploy-hook /opt/shifty/scripts/cert-deploy-hook.sh`, which copies the certificates into `nginx/certs` and reloads nginx with `APP_VERSION` from `.deploy/current`; `certbot renew --dry-run` passes.
- [ ] The `db` container was recreated once after adding the `pg_backups` volume (`docker compose exec db ls -ld /backups` works).
- [ ] `BACKUP_DIR` (`/var/backups/shifty`) exists on the host. `scripts/deploy.sh` creates it in the preflight if it can; a bind-type named volume does not create it, and without it `db` cannot be recreated.
- [ ] First deploy with the two Redis instances: `redis_state` starts empty once. Login lockouts, idempotency replays and pending OTP codes from before the switch are gone; tell the store owners that a code requested just before the deploy must be requested again.
- [ ] If this release changes `nginx/nginx.prod.conf` or the edge image, `make deploy-edge` is scheduled outside peak hours (`make deploy` only reloads the edge).
- [ ] At least one alert channel works (`ALERT_EMAIL` with msmtp/sendmail, or `ALERT_WEBHOOK_URL`): trigger a test alert with `SHIFTY_STATE_DIR=$(mktemp -d) BACKUP_DIR=$(mktemp -d) bash scripts/backup-check.sh` (the temporary state dir keeps the real alert from being silenced).

## 2. Observability and health

- [ ] Sentry is enabled for backend API and workers with the correct environment name and release identifier.
- [ ] `https://<domain>/api/ops/health/ready` returns 200 from the production ingress path (it checks Postgres and Redis; `/api/ops/health/live` does not).
- [ ] Error-rate, latency, worker-queue, webhook/outbox, and backup/drill alerts are active (`deploy/cron/shifty-latency`, `deploy/cron/shifty-guard`).
- [ ] Dashboard links for API health, database, Redis, background jobs, payments, and Sentry are included in release notes.
- [ ] The capacity acceptance test (`docs/PERF_ACCEPTANCE.md`) passed on staging with the release candidate: `scripts/perf_acceptance_check.py` printed `APROBADA` and its output, the runner used and the rate-limit setup are attached to the release notes. For the first launch it ran on the real VPS within the provider's 30-day guarantee window. Required for releases that touch availability, booking, the dashboard, reports, jobs or database configuration.

## 3. Database migrations

- [ ] Alembic has exactly one head before release.
- [ ] Migration SQL has been reviewed for destructive operations, long locks, table rewrites, and backfill volume.
- [ ] Every migration is expand-only for this release (contract steps ship one release later), indexes use `CONCURRENTLY` in an autocommit block, and constraints go `NOT VALID` + `VALIDATE`: the previous release must run against the new schema, or rollback is not possible.
- [ ] Migrations ran through `make deploy` (`compose run --rm --no-deps --no-build backend alembic upgrade head`, before recreating the app), not by hand on a running container.
- [ ] The deploy ran through `scripts/deploy.sh`, which passes `APP_VERSION` and uses `up --no-build --remove-orphans` (a renamed service, such as `redis` split into `redis_cache`/`redis_state`, otherwise leaves the old container holding its port).
- [ ] The migration role is a Postgres superuser: migration `b2c4e6a8d0f3` runs `CREATE EXTENSION IF NOT EXISTS pg_stat_statements`, which is not a trusted extension (the library is preloaded by the compose `shared_preload_libraries`). With a non-superuser migration role the deploy stops at that revision.
- [ ] The pre-deploy data checks of `docs/DEPLOY_RUNBOOK.md` §5b returned 0 on production; any non-zero count stops the migrations.
- [ ] Post-migration schema version and application startup were verified.

## 4. Backup, restore, RPO, and RTO

- [ ] A fresh backup exists before migration or any irreversible data operation.
- [ ] Backup artifact and checksum are stored outside the application host.
- [ ] Current restore drill evidence is available and not older than 31 days.
- [ ] The drill verifies as the app role: its evidence has a `verify-app-role` step with `ok: true` (grants, no `BYPASSRLS`, timeouts of `shifty_app`), not only the owner's `verify-restore`.
- [ ] RPO target is `<= 24h`; latest restorable backup age is within that target.
- [ ] RTO target is `<= 4h`; most recent drill duration is within that target or has an approved exception.
- [ ] Restore owner and escalation path are listed in the release notes.

## 5. Payments and rate limiting

- [ ] Payment provider is in the intended mode, webhook endpoint is active, and webhook signing secret matches production.
- [ ] Payment idempotency, reconciliation, and failure-alert paths were smoke tested.
- [ ] Rate limiting is enabled at the API/proxy layer for public and auth-sensitive endpoints.
- [ ] Trusted proxy/header settings match the actual ingress topology.

## 6. Release, smoke test, and rollback

- [ ] Deployment artifact/image/tag is immutable and recorded: the git sha passed as `make deploy APP_VERSION=<sha>`, also in `.deploy/current`.
- [ ] `.github/workflows/security-scan.yml` is green on the commit being deployed (pip-audit on `backend/uv.lock`, Trivy on the three images). Every entry in `backend/.pip-audit-ignore` or `.trivyignore` has an owner-approved reason.
- [ ] Smoke tests cover login, appointment read/write, reporting, payment webhook path, and worker processing.
- [ ] After the deploy, `docker compose exec rabbitmq rabbitmq-diagnostics alarms` reports no alarms (the deploy gate checks it). The prod broker runs with a 384M memory limit, an absolute watermark of 280MiB and `+S 2:2`: with the alarm on, publishers block and OTP mails stop.
- [ ] Rollback target is known: `.deploy/previous` (what `make rollback` deploys, without migrating), previous environment values, and the forward-fix plan for the migration.
- [ ] Rollback trigger thresholds are defined for error rate, latency, failed payments, failed workers, and failed health checks.
- [ ] Release notes include owner, time window, risks, checklist exceptions, and exact verification evidence.
