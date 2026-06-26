# Release Checklist (Shifty)

Use this checklist for every production release. A release is ready only when each active item is checked or has an explicit owner-approved exception recorded in the release notes.

## 1. Configuration and secrets

- [ ] Production environment variables match `.env.production.example` and the deployment platform values.
- [ ] `DATABASE_URL`, `REDIS_URL`, JWT/auth secrets, payment provider secrets, Sentry DSN, SMTP/webhook secrets, and admin bootstrap credentials are present only in the secret manager.
- [ ] No production secret is committed, pasted in logs, or stored in local shell history.
- [ ] Secret rotation impact has been reviewed for long-lived workers and scheduled jobs.

## 2. Observability and health

- [ ] Sentry is enabled for backend API and workers with the correct environment name and release identifier.
- [ ] `/health` or the configured health endpoint returns healthy from the production ingress path.
- [ ] Error-rate, latency, worker-queue, webhook/outbox, and backup/drill alerts are active.
- [ ] Dashboard links for API health, database, Redis, background jobs, payments, and Sentry are included in release notes.

## 3. Database migrations

- [ ] Alembic has exactly one head before release.
- [ ] Migration SQL has been reviewed for destructive operations, long locks, table rewrites, and backfill volume.
- [ ] `make migrate` or the production migration command has been run against the target environment.
- [ ] Post-migration schema version and application startup were verified.

## 4. Backup, restore, RPO, and RTO

- [ ] A fresh backup exists before migration or any irreversible data operation.
- [ ] Backup artifact and checksum are stored outside the application host.
- [ ] Current restore drill evidence is available and not older than 31 days.
- [ ] RPO target is `<= 24h`; latest restorable backup age is within that target.
- [ ] RTO target is `<= 4h`; most recent drill duration is within that target or has an approved exception.
- [ ] Restore owner and escalation path are listed in the release notes.

## 5. Payments and rate limiting

- [ ] Payment provider is in the intended mode, webhook endpoint is active, and webhook signing secret matches production.
- [ ] Payment idempotency, reconciliation, and failure-alert paths were smoke tested.
- [ ] Rate limiting is enabled at the API/proxy layer for public and auth-sensitive endpoints.
- [ ] Trusted proxy/header settings match the actual ingress topology.

## 6. Release, smoke test, and rollback

- [ ] Deployment artifact/image/tag is immutable and recorded.
- [ ] Smoke tests cover login, appointment read/write, reporting, payment webhook path, and worker processing.
- [ ] Rollback target is known: previous image/tag, previous environment values, and migration rollback/forward-fix plan.
- [ ] Rollback trigger thresholds are defined for error rate, latency, failed payments, failed workers, and failed health checks.
- [ ] Release notes include owner, time window, risks, checklist exceptions, and exact verification evidence.
