# Capacity acceptance test (Shifty)

The go/no-go test for the 200-user target (plan de corrección §9, plan-capacidad §5). It runs a realistic mix against a seeded staging and a script decides whether it passed. Nobody reads the verdict off a chart.

| Piece | File |
| --- | --- |
| Seed: 200 stores `cap-001` … `cap-200`, 90 days of history | `backend/scripts/seed_capacidad.py` |
| Load scenario (Locust) | `backend/loadtests/locust_aceptacion.py` (pure helpers in `aceptacion.py`) |
| Verdict over Locust's `--csv` output | `backend/scripts/perf_acceptance_check.py` |
| CI (manual, nightly opt-in) | `.github/workflows/perf-acceptance.yml` |
| Per-PR guard: SQL statements per hot endpoint | `backend/tests/postgres/test_pg_presupuesto_de_sentencias.py` |

Locust is already in the `dev` group of `backend/pyproject.toml` and in `uv.lock`: nothing new to install.

## 1. What runs

200 concurrent users: a 5-minute ramp, then 20 minutes at full load. The 20 minutes cover four cycles of the 5-minute availability cache TTL, several beat cycles and one access-token refresh.

| Profile | Users | Think time | Flow |
| --- | --- | --- | --- |
| Public client | 150 | 2-8 s | random store → `stores/{slug}` → `services` → `staff` → `availability` for 2-4 dates in the next 14 days → `deposit/preview` → 30 % book a free slot (no email, so the `.noreply` technical address is used and no mail goes out) |
| Owner | 45 | 3-10 s | login once → dashboard and notifications → agenda for today and tomorrow → confirm or cancel appointments → edit store name and phone → edit a service → create a block 60-110 days out → `auth/refresh` every 14 min |
| Superadmin | 5 | 5-15 s | paginated store list → store detail → edit a `cap-` store's name |
| Burst | 10 at once | every 5 min | 10 bookings of the SAME slot (15-40 days out, outside the clients' window): expects 1 × 201 and 9 × 409 |

Not covered: OTP self-service (needs the OTP code, `OTP_PROVIDER=console` only), logo upload, and bookings with a Mercado Pago deposit (staging has no MP credentials; the plan gives that path its own threshold).

When the plateau starts, the scenario resets Locust's statistics, so the CSV p95 is the full-load p95, not the ramp. During the run it samples `/ops/slo` every 30 s as the superadmin.

Output next to the `--csv` prefix:

- `<prefix>_stats.csv` (Locust): p95 per route and global.
- `<prefix>_codigos.json`: HTTP status codes per route, connection errors, and each burst's result.
- `<prefix>_slo.jsonl`: one `/ops/slo` sample per line.

## 2. Pass criteria

`perf_acceptance_check.py` exits 0 when everything holds, 1 when any criterion fails (it prints each `FALLA`), and 2 when an input is missing.

| Criterion | Threshold |
| --- | --- |
| p95 per route with ≥ 20 samples | < 500 ms (`--p95-ms`) |
| p95 global (Aggregated row) | < 500 ms |
| Login p95 (bcrypt, 12 rounds) | < 1 s (`--login-p95-ms`) |
| Excluded from p95 | `/reports/export` and the burst requests |
| 5xx, 429, connection errors | 0 (a 409 outside the burst is legitimate: the slot was taken between availability and booking) |
| Each burst | exactly 1 × 201, the rest 409, at least one burst recorded |
| Every SLO sample | `oldest_pending_outbox_seconds` and `oldest_pending_email_send_seconds` ≤ 120 s; `outbox_budget_drops` = 0 if the metric exists |
| Memory (optional `--docker-stats` log) | every container < 70 % of its limit |

`outbox_budget_drops` does not exist as a metric today: since F2-03 a mail the dispatch budget cannot reach stays as a pending `email.send` row, so its age (`oldest_pending_email_send_seconds`) is the signal. The check also accepts the named metric if a later phase adds it.

Checked by hand after the run (the script does not see the host): no container restarted (`docker inspect -f '{{.Name}} {{.RestartCount}}' $(docker ps -q)` before and after), no OOM in `dmesg`, `numbackends` < 70 and no `idle in transaction` over 5 s in `pg_stat_activity`, and no overlapping active appointments.

## 3. Staging setup (once per test)

Never against production: the seed creates owner accounts with a known password, and the test writes. The seed refuses to run when `ENV` or the loaded settings say production.

1. Staging per `docs/DEPLOY_RUNBOOK.md` §6, with SMTP pointed at a sink or disabled and no Mercado Pago credentials.
2. Rate limits. Every request comes from the load generator's IP. The edge (`nginx.prod.conf`) allows 20 r/s per IP on `/api/` (burst 40) and 3 r/s on `/api/auth/`; the app allows 120 requests/min per IP for public reads. The mix produces roughly 40-60 r/s, so either use several source IPs or raise the limits in staging only (`RATE_LIMIT_PUBLIC_READ_PER_MINUTE` and the staging nginx `limit_req` zones). Keep `RATE_LIMIT_ENABLED=true` in staging so the Redis cost is measured. Nothing of this goes to the production `.env`; the rule-17 guards stay as they are. Write down which option was used next to the results.
3. Superadmin: `scripts/bootstrap_superadmin.py` with `SUPERADMIN_EMAIL` and `SUPERADMIN_PASSWORD` from the environment.
4. Seed, first with 5 stores to validate, then the 200. Inside the staging backend container:

   ```bash
   APP_VERSION=$(cat .deploy/current) docker compose exec -T \
     -e ENV=staging -e SEED_OWNER_PASSWORD="$SEED_OWNER_PASSWORD" backend \
     python scripts/seed_capacidad.py --stores 200 --manifest /tmp/capacidad.json
   ```

   Each store is one transaction; a store whose slug already exists is left alone and only listed in the manifest, so re-running is safe. The manifest has public ids and owner emails, no passwords. Seed close to the test day: the "next 14 days" are counted from the seed date.
5. Cleanup is not automated. Deleting data is the owner's call: drop the staging database or volume when the test is over.

## 4. Running it

### Against staging, by hand

From a machine that is NOT the VPS, in `backend/`:

```bash
python loadtests/aceptacion.py --host https://staging.example.com/api --out manifiesto.json
export SHIFTY_MANIFEST=manifiesto.json SEED_OWNER_PASSWORD=... \
       SHIFTY_SUPERADMIN_EMAIL=... SHIFTY_SUPERADMIN_PASSWORD=...
uv run locust -f loadtests/locust_aceptacion.py --headless \
  --host https://staging.example.com/api --csv run/aceptacion --only-summary
uv run python scripts/perf_acceptance_check.py --csv-prefix run/aceptacion \
  --docker-stats stats.log
```

`--host` carries the `/api` prefix. Use a single Locust process (no `--processes`): the burst and the SLO sampler run in the local runner.

To capture memory on the host during the run (same format as `scripts/checks.sh`):

```bash
while sleep 5; do
  docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.NetIO}}\t{{.BlockIO}}\t{{.PIDs}}' |
    sed "s/^/$(date -u +%Y-%m-%dT%H:%M:%SZ)\t/"
done >> stats.log
```

### Rehearsal against the local Docker stack

Useful to check the scenario, not to judge capacity (the numbers of a desktop mean nothing for the VPS). The local seed writes `cap-` stores into your local database.

1. Disable the app rate limit for the run: `RATE_LIMIT_ENABLED=false docker-compose up -d backend` (the dev compose reads it from the shell or `.env`; ENV is not production, so rule 17 does not apply). Put it back afterwards.
2. Seed a few stores and copy the manifest out:
   ```bash
   docker exec -e ENV=development -e SEED_OWNER_PASSWORD=... shifty-backend-1 \
     python scripts/seed_capacidad.py --stores 5 --manifest /tmp/capacidad.json
   docker cp shifty-backend-1:/tmp/capacidad.json manifiesto.json
   ```
3. Point Locust at `http://localhost/api` to go through nginx (the dev `nginx.conf` allows 200 r/s per IP, ten times production, so a single IP fits) or at the backend directly (`--host http://127.0.0.1:8000`) to leave the edge out.
4. Shorten the run with `SHIFTY_USUARIOS=20 SHIFTY_RAMPA_S=20 SHIFTY_MESETA_S=90 SHIFTY_RAFAGA_CADA_S=40 SHIFTY_THINK_SCALE=0.3`. These overrides exist only for rehearsals; the acceptance is judged with the plan's values.

Rehearsal on 2026-09-24 (3 stores, 20 users, 90 s plateau, local uvicorn): 1336 requests, 0 errors, two bursts of 1 × 201 + 9 × 409, 4 SLO samples, verdict `APROBADA`.

### From CI

`.github/workflows/perf-acceptance.yml` runs on `workflow_dispatch` and, only when the repo variable `PERF_NIGHTLY` is `true`, every night at 03:30 ART. Staging shares the VPS with production, so the nightly stays off until the owner decides otherwise. It builds the manifest from staging's public API by slug, runs Locust, runs the check and uploads `perf-acceptance` (CSV, codes, SLO samples, manifest) as an artifact even when it fails.

| Setting | Kind | What |
| --- | --- | --- |
| `STAGING_URL` | secret | staging API URL with `/api` |
| `SEED_OWNER_PASSWORD` | secret | the password the seed ran with |
| `SHIFTY_SUPERADMIN_EMAIL`, `SHIFTY_SUPERADMIN_PASSWORD` | secrets | a staging superadmin (samples `/ops/slo`) |
| `PERF_RUNNER` | variable | runner label; default `ubuntu-latest` |
| `PERF_NETWORK_OFFSET_MS` | variable | ms added to the p95 thresholds |
| `PERF_NIGHTLY` | variable | `true` to enable the nightly run |

Runner location matters. A GitHub-hosted runner is in the US and adds 120-150 ms of round trip to Argentina on every request: with it, a 500 ms threshold is really judging 350 ms of server time. Either register a self-hosted runner close to the VPS (Argentina or Brazil) and set `PERF_RUNNER` to its label, or set `PERF_NETWORK_OFFSET_MS=150` (or pass `network_offset_ms` when dispatching) so the thresholds are raised by the network cost. Write down which one was used.

## 5. Reading the results

- `FALLA p95 de GET /dashboard/summary: 620 ms >= 500 ms (90 muestras)`: that route is over. Look at its statement count first (`test_pg_presupuesto_de_sentencias.py` prints it), then at `scripts/pg_top_queries.py` on staging for the slowest statements.
- `FALLA 5xx: ...` or `429: ...`: open `<prefix>_codigos.json` for the route; 429 in a single-IP run usually means the limits of §3.2 were not raised.
- `FALLA rafaga N: ...`: two 201s is a double booking (the GiST exclusion or the lock failed) and blocks the release; a 5xx inside the burst is a lock or deadlock handled as an error.
- `FALLA SLO ...`: the outbox or the mail dispatch fell behind under load; check the Celery worker and `process_outbox_batch` logs for that window.
- Locust's own failure count also includes business answers marked as failures; the check script is the verdict, not Locust's exit code.

## 6. When to run it

Run the full test on the real VPS **within the provider's 30-day guarantee window**: if the host cannot hold 200 users, that is the moment to change the plan or the provider at no cost. After launch, run it before any release that touches availability, booking, the dashboard, reports, jobs or the database configuration, and keep the verdict output with the release notes (`docs/RELEASE_CHECKLIST.md` §2).

Per PR, the cheap guard is `tests/postgres/test_pg_presupuesto_de_sentencias.py` in the `backend-postgres` job: it pins how many SQL statements each hot endpoint sends. Lowering a ceiling after an optimization is a one-line change; raising one needs a reason in the PR.
