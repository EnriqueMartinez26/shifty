# Backup and Restore Runbook (Shifty)

This runbook defines the minimum production expectations for database backups, restore drills, and recovery evidence.

## Recovery targets

| Target | Expectation | Evidence |
| --- | --- | --- |
| RPO | `<= 24h` maximum acceptable data loss. | Latest restorable backup timestamp and checksum. |
| RTO | `<= 4h` maximum time to restore service from backup. | Restore drill start/end timestamps and result JSON. |
| Drill cadence | At least monthly; evidence must not be older than 31 days for a release. | `backup-drill-evidence` artifact or stored JSON record. |

If either target is missed, stop the release unless the release owner records an explicit exception and rollback/mitigation plan.

## Requirements

- PostgreSQL client tools installed (`pg_dump`, `pg_restore`).
- Source database URL available as `DATABASE_URL` or `BACKUP_DATABASE_URL`.
- Isolated drill/restore database URL available as `DRILL_DATABASE_URL`.
- Backup storage outside the application host.
- Access to the deployment health checks and operational dashboards.

## Manual backup

Run from the `backend` directory:

```bash
python scripts/backup_db.py --output-dir ../backups
```

Expected output:

- `shifty-YYYYMMDDTHHMMSSZ.dump`
- `shifty-YYYYMMDDTHHMMSSZ.sha256`

Store both files together. The checksum is part of the restore evidence, not decoration.

## Manual restore

Restore into an isolated validation database first. Do not restore directly into production unless this is an approved incident response action.

```bash
python scripts/restore_backup.py --backup-file ../backups/shifty-YYYYMMDDTHHMMSSZ.dump
```

After restore, run health checks for:

- Admin login.
- Appointment calendar read path.
- Reporting read path.
- Worker/webhook processing if the release touches async or payment flows.

## Monthly restore drill

1. Select the latest production backup.
2. Verify the backup checksum is present.
3. Restore into an isolated staging/drill database.
4. Run the health checks listed above.
5. Record evidence:
   - start and finish timestamp,
   - backup file and checksum file,
   - restore command result,
   - health-check result,
   - incidents or exceptions,
   - measured restore duration for RTO tracking.

## Automated drill

- Workflow: `.github/workflows/monthly-backup-drill.yml`
- Schedule: first day of each month (`cron: 0 5 1 * *`) and manual dispatch.
- Evidence: `backup-drill-evidence` artifact with JSON and checksums.

Required secrets:

- `BACKUP_DATABASE_URL`
- `DRILL_DATABASE_URL`

## Proxy and edge hardening

- `TRUST_PROXY_HEADERS=true` only when the API is behind a trusted proxy such as Cloudflare, Nginx, or Traefik.
- Use `TRUST_PROXY_HEADERS=false` when the API is directly exposed to the internet.
- Enforce TLS at the edge/proxy.
- Limit HTTP methods and request body size at the proxy.
- Enable WAF and edge rate limiting.

## Minimum alerts

- API error rate above 1%.
- Abnormal p95 latency.
- Webhook/outbox queue accumulation.
- Periodic expiration or outbox processing failures.
- Missing backup or stale restore-drill evidence.
