# Backup and Restore Runbook (Shifty)

This runbook defines the production expectations for database backups, restore drills, and recovery evidence.

## Recovery targets

| Target | Expectation | Evidence |
| --- | --- | --- |
| RPO | `<= 24h` maximum acceptable data loss. | `/var/backups/shifty/last-success` (written only after the off-host copy) and the bucket listing. |
| RTO | `<= 4h` maximum time to restore service from backup. | Restore drill start/end timestamps and result JSON. |
| Drill cadence | At least monthly; evidence must not be older than 31 days for a release. | `backup-drill-evidence` artifact or stored JSON record. |

The RPO is achievable since 2026-09-24 (plan F0-20): a systemd timer takes a daily dump at 03:00 Argentina time and copies it off the host. Before that there was no scheduled backup at all.

If either target is missed, stop the release unless the release owner records an explicit exception and rollback/mitigation plan.

## Daily backup on the host

What runs (`scripts/backup.sh`, triggered by `deploy/systemd/shifty-backup.timer`):

1. `docker compose exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fd -j 2 --compress=zstd:3 -f /backups/daily/shifty-<UTC timestamp>`. It runs inside the `db` container as the **owner role** over the local socket. It never uses `DATABASE_URL`: that is the `shifty_app` role, without `BYPASSRLS`, and under RLS `pg_dump` aborts or dumps only what the policies let it see.
2. `globals.sql` inside the same directory: `pg_dumpall --globals-only --no-role-passwords`. Roles are cluster objects, so the database dump does not carry `shifty_app` nor its `ALTER ROLE ... SET` timeouts; this file does, without password hashes. It is a reference for rebuilding the cluster, not something to replay blindly (see Restore).
3. `SHA256SUMS` inside the dump directory (one line per file, `globals.sql` included).
4. On Sundays (`BACKUP_WEEKLY_DAY=7`) a hard-linked copy goes to `weekly/`.
5. `rclone copy` of the new dump directory (`globals.sql` and `SHA256SUMS` included) to `${BACKUP_REMOTE}/daily/` (and `/weekly/`).
6. Retention: 7 daily and 4 weekly. On the host by **count** (the newest N are kept, so failing backups never delete the last good ones). In the bucket by age (`rclone delete --min-age 7d` / `28d`), and only after a new dump was uploaded.
7. `/var/backups/shifty/last-success` (`<epoch> <name>`). Without `BACKUP_REMOTE` the local dump is still taken, but the run fails and `last-success` is not written (set `BACKUP_ALLOW_LOCAL_ONLY=1` only on staging).

Any failure sends an alert (`ALERT_EMAIL` and/or `ALERT_WEBHOOK_URL`). `scripts/backup-check.sh` runs every hour from cron and alerts when `last-success` is older than 26 h (critical after 48 h). `scripts/deploy.sh` refuses to migrate when it is older than 24 h.

### Compose volume

The dump is written to a named volume mounted at `/backups` in the `db` service and bound to `/var/backups/shifty` on the host, so the host scripts can checksum and upload it. `docker-compose.prod.yml` needs this (if it is missing, `scripts/backup.sh` stops with "el volumen /backups del servicio db no apunta a BACKUP_DIR"); the `volumes` list of `db` is merged with the base file, which keeps `postgres_data`.

```yaml
services:
  db:
    volumes:
      - pg_backups:/backups

volumes:
  pg_backups:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: ${BACKUP_DIR:-/var/backups/shifty}
```

The host directory must exist before `docker compose up` (`install -d -m 0700 /var/backups/shifty`); a bind volume does not create it. The running `db` container only gets the mount when it is recreated, and `make deploy` never recreates `db`: do it once, in a maintenance window, with `APP_VERSION=$(cat .deploy/current) docker compose up -d --no-deps --no-build db` (`docs/DEPLOY_RUNBOOK.md` §1).

### One-time setup on the VPS (owner)

1. Create the bucket (Cloudflare R2 or Backblaze B2, S3-compatible) and an access key limited to that bucket. The bucket is the only part that needs an account (plan §7, decision 24).
2. Install rclone from the distribution or rclone.org, then `rclone config` a remote (for example `r2`). Check with `rclone lsd r2:`.
3. `install -d -m 0700 /var/backups/shifty /var/lib/shifty /var/log/shifty /etc/shifty`.
4. `cp deploy/ops.env.example /etc/shifty/ops.env && chmod 600 /etc/shifty/ops.env`, then set `BACKUP_REMOTE`, `DOMAIN` and `ALERT_EMAIL` or `ALERT_WEBHOOK_URL`. For mail alerts, install and configure `msmtp` (or any `sendmail`) with the existing SMTP account.
5. Install the units and enable the timer:

   ```bash
   install -m 0644 deploy/systemd/shifty-backup.service deploy/systemd/shifty-backup.timer /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now shifty-backup.timer
   systemctl start shifty-backup.service     # first run, now
   journalctl -u shifty-backup --since today
   cat /var/backups/shifty/last-success
   ```

   The units assume the clone lives in `/opt/shifty`; edit `WorkingDirectory` and `ExecStart` if it does not.
6. Install the cron files: `install -m 0644 deploy/cron/shifty-guard deploy/cron/shifty-latency /etc/cron.d/` and `install -m 0644 deploy/logrotate/shifty /etc/logrotate.d/shifty`.

Note: `--compress=zstd:3` was verified with `postgres:16.14-alpine` in the 2026-09-24 drill. Only a different image built without zstd would need `BACKUP_COMPRESS=gzip:6` in `/etc/shifty/ops.env`.

## Manual backup

On the VPS: `make backup` (the same script as the timer).

From a machine that reaches the database over the network (the monthly drill does this), run from the `backend` directory:

```bash
BACKUP_DATABASE_URL=postgresql://<owner>:<password>@<host>:5432/<db>?ssl=require \
  python scripts/backup_db.py --output-dir ../backups
```

`backup_db.py` reads `--database-url`, `BACKUP_DATABASE_URL` or `MIGRATION_DATABASE_URL`, in that order, and refuses the app role (the same URL as `DATABASE_URL`, or the `APP_DB_USER`/`shifty_app` user). Output: `shifty-YYYYMMDDTHHMMSSZ.dump` (custom format) and its `.sha256`.

## Restore

Restore into an isolated validation database first. Do not restore directly into production unless this is an approved incident response action.

### Before restoring into a new cluster (mandatory)

Verified in the 2026-09-24 drill (`postgres:16.14-alpine`). The dump keeps the `GRANT`s and default ACLs for `shifty_app` (neither `pg_dump` nor `pg_restore` uses `--no-privileges` since that drill: with it, the restored database had 0 grants for `shifty_app` and the app got "permission denied" everywhere). That only works if the target cluster is ready:

1. **Same `POSTGRES_USER` as the source** (`shifty_user` unless `.env` says otherwise). The dump carries `ALTER DEFAULT PRIVILEGES FOR ROLE shifty_user`; with a different owner, `pg_restore --exit-on-error` aborts.
2. **`shifty_app` exists BEFORE `pg_restore`.** Otherwise `--exit-on-error` aborts at `GRANT USAGE ON SCHEMA public TO shifty_app` and leaves a half-restored database.
3. **The role settings are applied, as a superuser** (on PostgreSQL 16 setting `NOBYPASSRLS` needs one). They are cluster-level and are not in the dump (migration `c2e4f6a8b0d1_app_role_timeouts`):

   ```sql
   CREATE ROLE shifty_app LOGIN PASSWORD '<APP_DB_PASSWORD>'
     NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
   ALTER ROLE shifty_app SET statement_timeout = '30s';
   ALTER ROLE shifty_app SET lock_timeout = '5s';
   ALTER ROLE shifty_app SET idle_in_transaction_session_timeout = '60s';
   ```

   Feed it to `psql` through stdin, not `-c`, so the password stays out of the process list and shell history. Or let `restore_backup.py --create-app-role` do it (it reads `APP_DB_PASSWORD` and never prints it). `globals.sql` in each daily dump directory shows the source's roles and settings for comparison; it has no passwords, so it is not a drop-in replacement for this step. It starts with a `\restrict <key>` line (added by `pg_dumpall` 16.10+), so only a `psql` of that era can replay it.

`restore_backup.py` checks step 2 and refuses to restore when the role is missing. A scratch database in the **same** cluster (the example below) already has both roles.

### From the daily dump (directory format)

```bash
# 1. Get the dump (skip if it is still on the host).
rclone copy r2:shifty-backups/prod/daily/shifty-<ts> /var/backups/shifty/restore/shifty-<ts>
# 2. Verify it.
cd /var/backups/shifty/restore/shifty-<ts> && sha256sum -c SHA256SUMS
# 3. Restore into a scratch database in the same container.
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" shifty_restore_check'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d shifty_restore_check -j 2 --no-owner --exit-on-error /backups/restore/shifty-<ts>'
# 4. Check it as the owner (schema and data) AND as the app (grants).
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d shifty_restore_check -Atc "select version_num from alembic_version; select count(*) from appointments"'
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d shifty_restore_check -Atc "set role shifty_app; select count(*) from stores"'
docker compose exec -T db sh -c 'dropdb -U "$POSTGRES_USER" shifty_restore_check'
```

The `set role shifty_app` query must return a number, not "permission denied". Under RLS without a store context the count can be 0; this check is about grants.

`-j 2` matches the backup (`BACKUP_JOBS=2`) and the VPS size. Measured RTO in the 2026-09-24 drill: about 20 s for a 316 KB dump (restore plus checks, local). That is a floor, not a forecast: restore time grows roughly with data and index size, so re-measure in each monthly drill and keep the `duration_seconds` of the evidence against the 4 h target.

### From a custom-format dump (`backup_db.py`)

```bash
python scripts/restore_backup.py --backup-file ../backups/shifty-YYYYMMDDTHHMMSSZ.dump
# New cluster without shifty_app: create it first (reads APP_DB_PASSWORD).
APP_DB_PASSWORD=... python scripts/restore_backup.py --create-app-role --backup-file ...
```

`restore_backup.py` uses `DATABASE_URL` or `--database-url` as the target and `APP_DB_USER` (default `shifty_app`) as the app role. With `--create-app-role` the target URL must be a **superuser** of the target cluster: on PostgreSQL 16 `CREATE ROLE ... NOBYPASSRLS` and `ALTER ROLE ... NOBYPASSRLS` need it. It creates the role when missing and, in both cases, sets `NOSUPERUSER NOBYPASSRLS` and the three timeouts. It never changes the password of an existing role, and it refuses when `APP_DB_USER` is the same user as the connection (it would strip the cluster's own superuser).

### Optional: boot the app against the restored database

The only end-to-end proof that RLS, grants and role settings fit together. Point a backend at the restored database with the **app** role (a staging compose project, or `docker compose run --rm --no-deps -e DATABASE_URL=postgresql+asyncpg://shifty_app:<APP_DB_PASSWORD>@db:5432/shifty_restore_check?ssl=disable backend ...`) and check `/health/ready` plus an admin login.

After restore, run health checks for:

- Admin login.
- Appointment calendar read path.
- Reporting read path.
- Worker/webhook processing if the release touches async or payment flows.

## Monthly restore drill

1. Select the latest production backup.
2. Verify the backup checksum.
3. Restore into an isolated staging/drill database, with the target cluster prepared as in "Before restoring into a new cluster".
4. Verify as the **app role**, not only as the owner: the owner can read a database the app cannot (2026-09-24). Then run the health checks listed above.
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
- What `backup_restore_drill.py` checks after the restore: `verify-restore` (as the owner: `alembic_version` and the critical tables) and `verify-app-role` (the privileges of `APP_DB_USER`/`shifty_app`: not superuser, no `BYPASSRLS`, the three timeouts in `rolconfig`, `USAGE` on `public`, and `SELECT`/`INSERT`/`UPDATE`/`DELETE` on every table plus `USAGE`/`SELECT` on every sequence). Either one failing fails the drill.
- The workflow runs the drill with `--create-app-role`, so it is self-sufficient: it creates `shifty_app` in the target when missing, with the `APP_DB_PASSWORD` secret. That secret is required; the first step fails naming it when it is empty.

Required secrets (the first step fails with an explicit error naming the missing ones):

- `BACKUP_DATABASE_URL`: the **owner** role of the source database, never the app role.
- `DRILL_DATABASE_URL`: a separate database to restore into. The drill refuses to restore onto the source (same host, port and database name).
- `APP_DB_PASSWORD`: the password the drill uses to create `shifty_app` in the target when it is missing.

Where it runs: production publishes no database port (`ports: !reset []` in `docker-compose.prod.yml`), so a GitHub-hosted runner cannot reach it. Run the drill on a self-hosted runner on the VPS, or point both secrets at staging (the second compose project, see `docs/DEPLOY_RUNBOOK.md`). Set the repository variable `BACKUP_DRILL_RUNNER` to the runner label (for example `self-hosted`); without it the job uses `ubuntu-latest` and only works against a database reachable from the internet.

## Proxy and edge hardening

- `TRUST_PROXY_HEADERS=true` only when the API is behind a trusted proxy such as Cloudflare, Nginx, or Traefik.
- Use `TRUST_PROXY_HEADERS=false` when the API is directly exposed to the internet.
- Enforce TLS at the edge/proxy.
- Limit HTTP methods and request body size at the proxy.
- Enable WAF and edge rate limiting.

## Minimum alerts

- API 5xx rate above 0.1% and p95 latency above 500 ms per route (`scripts/latency-check.sh`, every 5 minutes).
- Webhook/outbox queue accumulation.
- Periodic expiration or outbox processing failures.
- Missing backup (`scripts/backup-check.sh`, hourly) or stale restore-drill evidence.
