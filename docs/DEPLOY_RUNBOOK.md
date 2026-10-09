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
| Host hardened, **first, before anything else**: a non-root sudo user, SSH with keys only and no root login, `ufw` allowing only 22/80/443, `unattended-upgrades` with security updates only and no automatic reboot, `fail2ban` for sshd, timezone UTC with chrony (see "Host: hardening" below) | `sudo bash scripts/host-hardening-check.sh` exits 0 and prints `endurecimiento: todo en orden`; `timedatectl` shows `Etc/UTC` and `System clock synchronized: yes` |
| Docker Compose >= 2.24 (`ports: !reset []` in `docker-compose.prod.yml`) | `docker compose version` |
| Server `.env` sets `COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` and `COMPOSE_PROJECT_NAME=shifty` | `docker compose config --services` lists the prod services without `-f` |
| Server `.env` does **not** set `APP_VERSION`. `docker-compose.prod.yml` requires it for every compose command (`${APP_VERSION:?}`); the deploy passes it and records it in `.deploy/current`, and the host scripts (backup, latency) read it from there. A value pinned in `.env` goes stale after the first deploy, and a bare `docker compose up -d` would bring that old version back | `grep -c APP_VERSION .env` is 0 |
| Server `.env` copied from `backend/.env.production.example` with every placeholder replaced. Mercado Pago and Sentry are **required** in production: `MERCADOPAGO_WEBHOOK_SECRET` (the webhook only verifies signatures with this global secret in production), `MERCADOPAGO_OAUTH_CLIENT_ID`, `MERCADOPAGO_OAUTH_CLIENT_SECRET` and `MERCADOPAGO_OAUTH_REDIRECT_URI` (stores link their account only through OAuth), all from the production Mercado Pago app (a `TEST-` client secret is rejected), and `SENTRY_DSN`. `docker-compose.prod.yml` refuses to start without them (`:?`), and the API and Celery refuse to boot if one is empty or still a placeholder (`core/config.py`). The boot also requires `https://` in `PUBLIC_API_URL` and in every `CORS_ORIGINS` origin, `OTP_PROVIDER=email` (the only implemented provider) and `OPS_ENABLE_PUBLIC_HEALTH=false`. Error messages name the variable, never its value | `docker compose config --quiet` exits 0; after the deploy, `docker compose logs backend` shows no `ValueError` |
| The deploy user is in the `docker` group (the scripts never use `sudo`) | `docker ps` as that user |
| `docker login ghcr.io` with a token that has `read:packages` (the packages are private) | `docker pull ghcr.io/enriquemartinez26/shifty-backend:latest` |
| `/etc/shifty/ops.env` from `deploy/ops.env.example` (`DOMAIN`, `BACKUP_REMOTE`, alerts, `RCLONE_CONFIG`, `DEPLOY_GITHUB_TOKEN` while the repository is private). Readable by root (backup timer, cron) **and** by `deploy` (`scripts/deploy.sh` never uses sudo): `/etc/shifty` root:deploy 0750, `ops.env` root:deploy 0640, `/var/backups/shifty` root:deploy 0750 (the deploy reads `last-success`). With root 0600/0700 the deploy ran without `ops.env` and could not see the backup (first deploy, 2026-10-08); an unreadable `ops.env` (or an `/etc/shifty` that `deploy` cannot enter) now logs an `AVISO`. With 0640 **every member of the `deploy` group reads the whole file**, token and alert webhook included: keep only the `deploy` user in that group and never add people to it "so they can deploy" | `sudo -u deploy test -r /etc/shifty/ops.env && sudo -u deploy test -r /var/backups/shifty/last-success && echo ok`; `getent group deploy` lists no extra members (`deploy:x:<gid>:`) |
| Daily backup timer enabled, rclone remote and bucket (`docs/BACKUP_RESTORE_RUNBOOK.md`) | `systemctl list-timers shifty-backup.timer`, `cat /var/backups/shifty/last-success` |
| Host cron installed: `deploy/cron/shifty-guard`, `deploy/cron/shifty-latency`, `deploy/cron/shifty-pg-top`, `deploy/logrotate/shifty` | `ls /etc/cron.d/shifty-*` |
| certbot on the host with webroot `/opt/shifty/nginx/acme` (compose mounts `./nginx/acme` at `/var/www/acme` in nginx) and `scripts/cert-deploy-hook.sh` as deploy hook | `certbot renew --dry-run` |
| After adding the `pg_backups` volume to `docker-compose.prod.yml`, the `db` container was recreated once so the volume attaches (see below) | `docker compose exec db ls /backups` |
| python3 on the host (the latency report is stdlib only) | `python3 --version` |
| Sending domain verified with the SMTP provider, with SPF, DKIM and DMARC published and the provider sandbox lifted (see "Mail deliverability" below) | a test OTP to a Gmail account shows `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS` |
| 2 GB swapfile with `vm.swappiness=10`, and Docker started at boot (see "Host: memory budget, swap and boot" below) | `swapon --show`, `sysctl vm.swappiness`, `systemctl is-enabled docker containerd` |
| The reboot test passed once (see below) | after `sudo reboot`, `APP_VERSION=$(cat .deploy/current) docker compose ps` shows every service `healthy` without anyone running `up` |

### Host: hardening

Once, on the fresh VPS, before installing Docker or cloning the repo. The steps assume **Ubuntu 24.04 LTS** (pick it as the OS template when the VPS is created); check with `cat /etc/os-release` and adapt them if the image is another release. Run them in order: the SSH step must be tested in a second session before the first one is closed, and the firewall must allow SSH before it is enabled.

**0. Update the base image**, as root (the password or key set in hPanel when the VPS was created):

```bash
apt update && apt full-upgrade -y
[ -f /var/run/reboot-required ] && reboot    # then log in again as root
```

**1. A non-root sudo user.** The steps use `deploy`, the user that later runs `make deploy` (it joins the `docker` group once Docker is installed). Every person who operates the server puts their own public key in its `authorized_keys`, one per line.

```bash
adduser --gecos "" deploy            # a long password, for sudo only: after step 2 SSH never accepts it
usermod -aG sudo deploy
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
# Reuse root's key if you added one in hPanel:
[ -s /root/.ssh/authorized_keys ] && cp /root/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
# Add every other person's PUBLIC key (ssh-ed25519 AAAA... name@laptop), one per line:
nano /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 0600 /home/deploy/.ssh/authorized_keys
```

From your machine, in a new terminal: `ssh deploy@<ip>`, then `sudo -v` (asks for the sudo password). Do not continue until both work. From here on, everything runs as `deploy` with `sudo`.

**2. SSH with keys only, no root.** A drop-in named `00-...` wins: sshd keeps the **first** value it reads for each option, and Ubuntu's `sshd_config` includes `/etc/ssh/sshd_config.d/*.conf` (in name order) before its own lines, so this file also beats a `50-cloud-init.conf` that some images ship with `PasswordAuthentication yes`.

```bash
sudo tee /etc/ssh/sshd_config.d/00-shifty-hardening.conf >/dev/null <<'EOF'
# Shifty: SSH with keys only, no root login (docs/DEPLOY_RUNBOOK.md section 1).
PubkeyAuthentication yes
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo sshd -t     # no output means valid; never reload a config that fails here
sudo sshd -T | grep -E '^(pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '
# pubkeyauthentication yes, passwordauthentication no, kbdinteractiveauthentication no, permitrootlogin no
sudo systemctl reload ssh     # the unit is `ssh` on Ubuntu; a reload keeps the open sessions
```

**Keep this session open.** In a second terminal, from your machine:

```bash
ssh deploy@<ip>                       # must log in
ssh root@<ip>                         # must fail: Permission denied (publickey)
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive deploy@<ip>
                                      # must fail: Permission denied (publickey)
```

Only when the first command logs in and the other two are refused, close the first session. If the second session cannot log in, undo it from the first one (`sudo rm /etc/ssh/sshd_config.d/00-shifty-hardening.conf && sudo systemctl reload ssh`), find the problem (usually the key or the permissions of `~/.ssh`) and repeat. If both sessions are lost, use the provider's web console in hPanel (browser terminal or recovery mode): it does not go through sshd. If `sshd -t` complains about a missing `/run/sshd`, run `sudo mkdir -p /run/sshd` and repeat.

**3. Firewall: only 22, 80 and 443.** Allow SSH before enabling, or the enable cuts the session.

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable              # answers "may disrupt existing ssh connections": 22 is already allowed
sudo ufw status verbose      # Status: active; Default: deny (incoming); only 22, 80, 443 (and their v6)
```

**Docker publishes ports around ufw.** For a published port Docker writes its own iptables rules (its chains in `FORWARD`, `DOCKER-USER` first), which run before ufw's: a container port published on the host is reachable from the internet even if ufw does not allow it. That is safe here only because **in production nothing publishes a port except nginx, on 80 and 443**, which ufw allows anyway: every other service has `ports: !reset []` in `docker-compose.prod.yml` (their development ports in `docker-compose.yml` are bound to `127.0.0.1`, and production removes them anyway), and `test_en_produccion_solo_nginx_publica_puertos` (`backend/tests/unit/test_compose_contract.py`) fails if that changes. Consequences:

- Never publish another port in production, not even "for a minute" to debug: use `docker compose exec`, or an SSH tunnel (`ssh -L`) to a port bound to `127.0.0.1`.
- Never set `"iptables": false` in Docker's `daemon.json` to "make ufw work": it breaks container networking.
- After the first deploy, check what listens publicly:

  ```bash
  cd /opt/shifty
  APP_VERSION=$(cat .deploy/current) docker compose ps --format '{{.Service}}: {{.Ports}}'   # only nginx shows 0.0.0.0:80 and :443
  sudo ss -tlnp     # on public addresses only sshd (22) and docker-proxy (80, 443); the rest on 127.0.0.x or ::1
  ```

**4. Automatic security updates, without automatic reboot.**

```bash
sudo apt install -y unattended-upgrades
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
sudo tee /etc/apt/apt.conf.d/52shifty-unattended-upgrades >/dev/null <<'EOF'
// Shifty: never reboot by itself; reboots are manual (docs/DEPLOY_RUNBOOK.md section 1).
Unattended-Upgrade::Automatic-Reboot "false";
EOF
# needrestart (installed on Ubuntu) runs after every apt run, unattended ones
# included, and may restart services that use an upgraded library. List only:
# a libc or openssl update must not restart containerd/docker at a random hour.
echo "\$nrconf{restart} = 'l';" | sudo tee /etc/needrestart/conf.d/50-shifty.conf
```

Security only: Ubuntu's `/etc/apt/apt.conf.d/50unattended-upgrades` allows the release pocket and the `-security` pockets by default, with the `-updates` line commented out. Leave it like that (an origin list cannot be shortened from another file, only extended). Check:

```bash
apt-config dump | grep -E '^APT::Periodic::|^Unattended-Upgrade::(Allowed-Origins|Origins-Pattern)::|Automatic-Reboot'
# Unattended-Upgrade "1", Automatic-Reboot "false", no origin ending in -updates, -proposed or -backports
sudo unattended-upgrade --dry-run --debug 2>&1 | grep -i 'allowed origins'
```

Docker Engine comes from `download.docker.com`, which is not an allowed origin: unattended-upgrades never upgrades it. Upgrade Docker by hand, in a maintenance window (it restarts every container).

**When to reboot by hand.** Some updates (kernel, libc, systemd, openssl) only take effect after a reboot; apt then creates `/var/run/reboot-required` and lists the packages in `/var/run/reboot-required.pkgs`. `scripts/host-hardening-check.sh` (hourly, from `checks.sh`) alerts once a day while that file exists. Reboot within a week for a kernel security fix, sooner if the advisory is critical: in a low-traffic window, never during a deploy (`ls .deploy/lock` must fail), with a fresh backup (`cat /var/backups/shifty/last-success`), then `sudo reboot` and the checks of the reboot test in "Host: memory budget, swap and boot" below.

**5. fail2ban for sshd.** With keys only nobody guesses a password; fail2ban cuts the scanners' noise in the logs and their load.

```bash
sudo apt install -y fail2ban python3-systemd
sudo tee /etc/fail2ban/jail.d/shifty-sshd.local >/dev/null <<'EOF'
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
sudo fail2ban-client status sshd     # Status for the jail: sshd
```

A person banned by mistake (several failed keys from the same IP) waits an hour, or someone else unbans them: `sudo fail2ban-client set sshd unbanip <ip>`.

**6. Timezone UTC and NTP.** The host stays on UTC: the application stores and computes in UTC and formats Argentine time itself (CLAUDE.md rule 24), the backup timer is pinned to UTC (`deploy/systemd/shifty-backup.timer`) and the scripts log in UTC. A wrong clock breaks tokens, the Mercado Pago webhook age window and the expirations; `scripts/checks.sh` alerts when `timedatectl` says the clock is not synchronized.

```bash
sudo timedatectl set-timezone Etc/UTC
sudo apt install -y chrony            # replaces systemd-timesyncd
sudo systemctl enable --now chrony
timedatectl                           # Time zone: Etc/UTC (UTC, +0000); System clock synchronized: yes; NTP service: active
chronyc tracking                      # Leap status: Normal
```

**7. Verify.** Once the repo is cloned at `/opt/shifty` (and from then on every hour, from `checks.sh`):

```bash
cd /opt/shifty
sudo bash scripts/host-hardening-check.sh     # endurecimiento: todo en orden (exit 0)
```

It needs root (`sshd -T`, `ufw status` and `fail2ban-client` do). It checks the EFFECTIVE sshd config (`sshd -T`, so a drop-in that re-enables passwords is caught), that no `Match` block in `/etc/ssh/sshd_config` or the files it includes sets `PasswordAuthentication`, `KbdInteractiveAuthentication` or `PermitRootLogin` to anything but `no` (a `Match` that applies overrides the global value, and `sshd -T` cannot see one for another user, group or network), that ufw is active, denies incoming by default and opens nothing but `HARDENING_UFW_ALLOWED` (`22/tcp 80/tcp 443/tcp`), that unattended-upgrades is on with security origins only and no automatic reboot, that the fail2ban `sshd` jail is up, and whether a reboot is pending. Every finding alerts like the other host scripts.

### Host: memory budget, swap and boot

The production VPS is a Hostinger KVM 2: **2 vCPU, 8 GB RAM, 100 GB NVMe**. Every container has a memory limit (`deploy.resources.limits` in `docker-compose.yml` and `docker-compose.prod.yml`), and the limits must add up to less than the RAM, also during a deploy: `scripts/deploy.sh` starts the new backend replicas **next to** the old ones before it stops the old ones. `test_la_memoria_de_produccion_entra_en_el_vps` (`backend/tests/unit/test_compose_contract.py`) sums the limits from the compose files and `deploy.sh` and fails above 6.5 GiB steady or 7 GiB (8 GiB minus 1 GiB for the system) at the deploy peak.

| Service | Before (16 GB host) | Now (8 GB host) | CPU limit |
| --- | --- | --- | --- |
| db (Postgres) | 4096M | 2560M | none (plan §8: CFS throttling adds p95 spikes) |
| backend | 3 x 512M | 2 x 512M | none (same reason) |
| celery_worker (2 children) | 768M | 768M | 1.5 -> 1.0 |
| celery_worker_interactive (1 child) | 256M | 256M | 0.5 (new) |
| celery_beat | 256M | 256M | 0.25 (new) |
| rabbitmq (alarm at 280 MiB) | 384M | 384M | none |
| redis_cache (`maxmemory 96mb`) | 192M | 192M | none |
| redis_state (`maxmemory 48mb`) | 96M | 96M | none |
| nginx | 256M | 256M | none |
| frontend | 64M | 64M | none |
| **Steady total** | **7904 MiB (7.7 GiB)** | **5856 MiB (5.7 GiB)** | |
| **Deploy peak** (steady + the new backend replicas) | **9440 MiB (9.2 GiB)** | **6880 MiB (6.7 GiB)** | |
| Left for the OS, Docker and page cache at the peak (of 8192 MiB) | none | 1312 MiB | |

- **Two backend replicas**, one per vCPU. `DEPLOY_BACKEND_REPLICAS` in `scripts/deploy.sh` must equal `deploy.replicas` in `docker-compose.prod.yml` (`test_el_deploy_levanta_tantas_replicas_como_produccion`).
- **Postgres** gets 2560M: `shared_buffers=640MB` (25 %), `effective_cache_size=1920MB` (75 %: the database's page cache is charged to its own cgroup, so it cannot use more than the limit), `work_mem=4MB`, `maintenance_work_mem=128MB`, `shm_size: 256m`.
- **`max_connections=100`**, from the deploy peak: (2 old + 2 new backend replicas) x (`DB_POOL_SIZE` 5 + `DB_MAX_OVERFLOW` 5) = 40, plus the Celery children (2 general + 1 interactive) x 10 = 30, total 70. Beat runs no tasks and the prefork parents dispose their pool before forking, so they add nothing. On top of that: the migration (2), the backup (2), the weekly `pg_stat_statements` report and a console (3) and the 3 connections Postgres reserves for the superuser: 80 of 100. Raising the pool, the replicas or the Celery concurrency means redoing this sum (`test_los_pools_de_produccion_entran_en_max_connections`).
- **CPU**: the API and the database have no CPU limit. Each Celery process does, and none gets more than half the host, so a runaway batch leaves at least one vCPU for the API and Postgres (`test_ningun_proceso_de_celery_deja_sin_cpu_a_la_api`).
- **Staging does not fit** next to production on this host (section 6).

Swap, once. It is a safety margin for a short spike, not memory to plan with: with `vm.swappiness=10` the kernel only swaps under real pressure, and `scripts/checks.sh` alerts when there is no swap or more than half of it is in use.

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-shifty-swap.conf
sudo sysctl -p /etc/sysctl.d/99-shifty-swap.conf
swapon --show            # /swapfile, 2G
sysctl vm.swappiness     # vm.swappiness = 10
```

Docker at boot, once. Every service has `restart: always`, so the stack comes back by itself only if the Docker daemon starts with the host:

```bash
sudo systemctl enable docker containerd
systemctl is-enabled docker containerd   # enabled, enabled
```

Reboot test, once before launch (and after any change to the host's boot setup), in a maintenance window: the site is down for the minute or two the reboot takes.

```bash
sudo reboot
# back on the host, without running any `up`:
cd /opt/shifty
APP_VERSION=$(cat .deploy/current) docker compose ps    # every service running and healthy (backend, workers and beat may take 1-2 min)
swapon --show                                           # the swapfile is active again
curl -fsS https://<domain>/api/ops/health/ready         # 200
systemctl list-timers shifty-backup.timer               # the backup timer is scheduled again
```

If a service is missing after the reboot, `docker compose ps -a` and `docker compose logs <service>` show why; do not paper over it with a manual `up`, because the next unattended reboot will have the same problem.

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

### Mail deliverability (SPF, DKIM, DMARC)

Production sends OTP codes, booking confirmations and reminders over SMTP with STARTTLS on port 587 (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` and `EMAILS_FROM_EMAIL` in the server `.env`; `docker-compose.prod.yml` refuses to start without them). Without SPF, DKIM and DMARC on the sending domain, Gmail and Outlook file that mail as spam or reject it, and a client who never sees the OTP cannot book. Do this once, before the first deploy; DNS changes can take hours to propagate.

In the records below, `<domain>` is the domain of `EMAILS_FROM_EMAIL` and everything in `<...>` is a placeholder: take the real values from the chosen provider's console, never from this page.

1. **Choose the provider.** Any SMTP relay with domain verification, DKIM signing and bounce handling works. Amazon SES is the cost reference (pay per message, no monthly minimum), not a decision. Below, "the chosen provider" is whatever is picked. `SMTP_USER`/`SMTP_PASS` are the provider's SMTP credentials (for SES, SMTP credentials generated in the console, not the IAM access keys).
2. **Verify the sending domain** with the provider (verifying a single address is not enough: DKIM signs per domain). The provider asks for one or more DNS records to prove ownership; on SES the DKIM records below double as the verification.
3. **Publish the DNS records** at the domain's DNS host:

   | Record | Name | Value (pattern) |
   | --- | --- | --- |
   | SPF (TXT) | the envelope sender (Return-Path) domain: `<domain>`, or the custom MAIL FROM subdomain if the provider uses one (e.g. `<bounce-subdomain>.<domain>`) | `v=spf1 include:<provider-spf-domain> -all` |
   | DKIM (CNAME or TXT, as the provider says) | `<selector>._domainkey.<domain>`, one per selector the provider gives | the CNAME target or the `v=DKIM1; k=rsa; p=<public-key>` value the provider gives |
   | DMARC (TXT) | `_dmarc.<domain>` | `v=DMARC1; p=none; rua=mailto:<reports-mailbox>@<domain>` |

   - A name has **at most one** SPF record. If `<domain>` already has one (for example for a mailbox provider), add the `include:` to it instead of creating a second record: two SPF records are a permanent error and SPF fails for both.
   - DMARC passes when SPF or DKIM passes **for the domain in the From header**. A provider that uses its own domain as Return-Path passes SPF for that domain, not for `<domain>`; then DKIM is the one that aligns. Configure a custom MAIL FROM subdomain on the provider if SPF should align too.
   - Start DMARC with `p=none` and read the aggregate reports that arrive at the `rua` mailbox for one or two weeks. When every legitimate source passes, move to `p=quarantine` (later `p=reject` if desired). Going straight to `quarantine` can send real mail to spam if a source was missed.
4. **From address.** `EMAILS_FROM_EMAIL` must be an address on the verified domain (for example `no-reply@<domain>`); with any other address the provider refuses to send or DMARC fails. Changing it is a change to the server `.env`, applied by recreating the app services on the running version (`APP_VERSION=$(cat .deploy/current) docker compose up -d --no-deps --no-build backend celery_worker celery_worker_interactive celery_beat`).
5. **Leave the sandbox.** Some providers start new accounts in a sandbox that only delivers to verified recipients and caps the daily volume (SES does). Request production access from the provider before the first deploy; the request asks for the kind of mail (transactional: codes, confirmations, reminders) and how bounces and complaints are handled.
6. **Verify end to end.** With the release deployed, request an OTP from a store's public booking page with a phone that is not yet a client of that store and a Gmail address (`OTP_PROVIDER` must not be `console`: production refuses it). In Gmail, open the message, then "Mostrar original" ("Show original"): the header summary must read `SPF: PASS`, `DKIM: PASS` and `DMARC: PASS`, with the DKIM domain equal to `<domain>`. If one fails, fix the record before going live; tools such as `dig TXT _dmarc.<domain>` and `dig TXT <selector>._domainkey.<domain>` (or `CNAME`) show what is published.

### First deploy on an empty host

`make deploy` assumes a running stack (it never starts db, redis, rabbitmq or nginx, and it wants a fresh backup). On a host with nothing running, the order that worked on 2026-10-08 is below. `<sha>` is the full sha being deployed; until `.deploy/current` exists every compose command needs it.

1. **Clone the private repository with a read-only deploy key**, as `deploy`: `ssh-keygen -t ed25519 -f ~/.ssh/shifty_repo -N ''`, add `~/.ssh/shifty_repo.pub` in GitHub under Settings → Deploy keys with "Allow write access" **off**, point `github.com` at that key in `~/.ssh/config` (`IdentityFile ~/.ssh/shifty_repo`, `IdentitiesOnly yes`) and `git clone git@github.com:EnriqueMartinez26/shifty.git /opt/shifty`. The key reads this one repository and nothing else.
2. **First TLS certificate, standalone** (nginx is not running yet, so port 80 is free and there is no webroot): `sudo certbot certonly --standalone -d <domain>`, then copy it into `nginx/certs` with the hook: `sudo env APP_VERSION=<sha> RENEWED_LINEAGE=/etc/letsencrypt/live/<domain> bash scripts/cert-deploy-hook.sh` (its reload step fails while nginx is down; the copy is what matters here).
3. **Infrastructure**: `APP_VERSION=<sha> docker compose up -d --no-build --wait db redis_cache redis_state rabbitmq`.
4. **The edge, alone**: `APP_VERSION=<sha> docker compose up -d --no-build --no-deps nginx` (`--no-deps`: nginx depends on backend and frontend, which the deploy starts; nginx resolves `backend` at request time, so it starts without them).
5. **Switch renewals to the webroot**, now that nginx serves `/.well-known/acme-challenge/`: `sudo certbot reconfigure --cert-name <domain> --webroot -w /opt/shifty/nginx/acme --deploy-hook /opt/shifty/scripts/cert-deploy-hook.sh` (it runs a dry-run renewal; `certbot renew --dry-run` confirms).
6. **First backup**, so the preflight finds `last-success`: `sudo env APP_VERSION=<sha> bash scripts/backup.sh`.
7. **Deploy**: `make deploy APP_VERSION=<sha>`. There is no previous version, so a failed gate cannot roll back.
8. **Edge record**: `scripts/deploy.sh edge` (`make deploy-edge`), so `.deploy/edge-conf.sha256` exists and later edge runs recreate nginx only when something changed.

## 2. Images (CI)

`.github/workflows/build-images.yml` runs when the `Quality` workflow (`quality.yml`) **finishes green on a push to `main`** (`workflow_run`), and by hand (`workflow_dispatch`). It checks out and tags the sha that Quality tested (`github.event.workflow_run.head_sha`; in a `workflow_run`, `github.sha` is the newest commit of `main`, which may be another one). A red Quality, a Quality of a pull request (even one from a fork whose branch is called `main`) or a cancelled run publishes nothing. It builds `backend`, `frontend` and `nginx` and pushes `ghcr.io/enriquemartinez26/shifty-<service>:<git sha>` plus `:latest`.

`workflow_run` gotchas: the run uses the workflow file of the default branch with the base repository's `GITHUB_TOKEN` (the job's `permissions`, `packages: write` included) and its `vars`, the same as the old `push` trigger; it only exists once merged to `main`, so a pull request cannot exercise it (after merging a change to this workflow, check in Actions that `Build images` started after `Quality` and tagged Quality's sha). The manual run skips the Quality gate (it builds whatever branch it is pointed at), which is why `scripts/deploy.sh` asks GitHub again before deploying (section 3). The backend image serves the API, the workers and beat. The VPS never builds: every `up` in `scripts/deploy.sh` carries `--no-build` and `--remove-orphans` (so a renamed service does not leave its old container behind), and the migration `run` cannot build because the production view has no `build` section, and after the pull the script checks with `docker image inspect` that every `image:tag` of `docker compose config --images` is present. The `retention` job deletes untagged versions and keeps the 5 newest per package; it never fails the build.

**Front build variables (GitHub repository variables).** The frontend bundle is static, so these are read at build time, not when the container starts: changing one means a new build (a merge to `main` once Quality passes, or a manual run of `build-images.yml`) and a deploy of that sha. Set them in GitHub under Settings → Secrets and variables → Actions → **Variables** (not Secrets: they end up in the public bundle anyway). `build-images.yml` passes them to `frontend/Dockerfile` as build args. The real values live only in those GitHub variables, never in code, docs, `*.example` files, commits or PRs: the repository is private today, but its visibility has changed before.

| Variable | Format | Used by | Empty or invalid |
|---|---|---|---|
| `VITE_SENTRY_DSN` | Sentry DSN of the frontend project | browser error reporting and `/sentry-tunnel` | Sentry off, tunnel answers 404 |
| `VITE_SUPPORT_WHATSAPP` | digits only, with country code, e.g. `549351XXXXXXX` (normalized by `shared/utils/whatsAppPhone.ts`) | "Renovar por WhatsApp" in the subscription banner; WhatsApp line of "Responsables y contacto" on `/legal/terminos` and `/legal/privacidad` | no WhatsApp link: the banner shows "Escribinos para renovar" (a `mailto:` if the email is set) and the legal line is omitted |
| `VITE_CONTACT_EMAIL` | one email address, e.g. `contacto@example.com` | email line (`mailto:`) of "Responsables y contacto"; the terms' "consultas" paragraph | line omitted; the terms keep the generic contact sentence |
| `VITE_LEGAL_RESPONSABLES` | free text, one or more full names (up to 300 characters) | "Responsables" line (Ley 25.326 art. 6) | line omitted |

If all three contact variables are empty, the legal pages show no "Responsables y contacto" block at all; a value that still looks like a template placeholder (`[[...]]`, `pendiente`, `change_me`) counts as empty. Domicilio and CUIT are not shown yet on purpose. A local `docker compose build frontend` reads the same names from the root `.env` (see `.env.example`). If the Vercel preview should show them too, set the same names in the Vercel project environment.

`docker-compose.prod.yml` references `ghcr.io/enriquemartinez26/shifty-<service>:${APP_VERSION}` for backend (API, workers and beat) and frontend. The production edge runs the base image `nginx:1.30.5-alpine` with `nginx/nginx.prod.conf` bind-mounted, so its image does not change per release; the `shifty-nginx` image CI publishes is not what production runs.

## 3. Deploy sequence (`scripts/deploy.sh deploy`)

1. **Lock** `.deploy/lock` (a second deploy stops; the guard does not restart containers while it exists).
2. **Preflight**, before touching anything:
   - `COMPOSE_FILE` (from the environment or the clone's `.env`) includes `docker-compose.prod.yml`. The script `cd`s into the clone first, so it can be called from anywhere.
   - `BACKUP_DIR` exists (created with mode 0750 if missing: the `pg_backups` volume is a bind and does not create it; if the `deploy` user cannot create it, the error suggests `install -d -o root -g deploy -m 0750`).
   - Compose >= 2.24 and `docker compose config -q` passes.
   - Every service in `DEPLOY_SERVICES` exists (default: `backend celery_worker celery_worker_interactive celery_beat frontend`; nginx is not in the list).
   - The `db` service is running (the deploy uses `--no-deps` and never starts or recreates db, redis or rabbitmq).
   - Disk under 80 %.
   - `/var/backups/shifty/last-success` is younger than 24 h (`DEPLOY_SKIP_BACKUP_CHECK=1` only on staging).
   - `Quality` passed on a push to `main` for `APP_VERSION`: the script asks GitHub's API (`/repos/EnriqueMartinez26/shifty/actions/workflows/quality.yml/runs?head_sha=<APP_VERSION>&branch=main&event=push&status=success`). The repository is **private**, so the API answers 404 without a token: set `DEPLOY_GITHUB_TOKEN` in `/etc/shifty/ops.env`, a fine-grained personal access token with access to this repository only and only the "Actions: read" permission, which is all that [listing workflow runs](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository) needs on a private repository. **Enrique (the owner) has to create it**: the repository belongs to a personal account (`EnriqueMartinez26`), and a collaborator cannot issue a fine-grained token for a repository they do not own (GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens; resource owner `EnriqueMartinez26`, "Only select repositories" → `shifty`, Repository permissions → Actions: Read-only). It is sent as `Authorization: Bearer` through curl's stdin (`curl -K -`), never on the command line (visible in `ps`), in the log or in the environment of docker, compose or any other child (`scripts/lib/common.sh` un-exports it right after loading `ops.env`), and a token with characters outside `[A-Za-z0-9_]` stops the preflight without printing it. **The token expires**: from that day every deploy stops at the preflight ("no pude preguntarle a GitHub ... vencido o sin \"Actions: read\"") until it is rotated; the rollback does not ask GitHub and keeps working. To rotate: before the expiry date the owner regenerates it (or creates an identical one), then on the VPS `sudoedit /etc/shifty/ops.env` replaces `DEPLOY_GITHUB_TOKEN` (keep root:deploy 0640), and `APP_VERSION=<a main sha> scripts/deploy.sh preflight`, run as `deploy`, confirms it. Without the token the query is anonymous, which only works while the repository is public (60 requests per hour per IP). `APP_VERSION` must be the full 40-character sha. If GitHub does not answer, the deploy stops (fail closed): retry, or, after checking the run in Actions by hand, `DEPLOY_SKIP_QUALITY_CHECK=1`, which deploys with an alert (meant for staging with a branch image).
3. Save the running version to `.deploy/previous` (from `.deploy/current`, or the tag of the running backend image on the first run).
4. `docker compose pull` of the app services, then `docker image inspect` of every expected `image:tag`. A failed pull or a missing image stops the deploy here, before migrating.
5. **Migrate before recreating**, with the old code still serving: `docker compose run --rm --no-deps -T backend alembic upgrade head`. If it fails, nothing was recreated. `run` takes no `--no-build` in any Compose version (only `up` and `create` do; Compose 5.5.1 rejects it as an unknown flag) and `run --pull never` needs Compose 2.33, above the 2.24 minimum. It still cannot build or pull: the production view has no `build` section (`build: !reset null`) and the previous step checked that the image is local.
6. **Backend, gradually**: `up -d --no-deps --no-build --remove-orphans --no-recreate --wait --scale backend=<old + 2> backend` starts 2 new replicas (`DEPLOY_BACKEND_REPLICAS`, equal to `deploy.replicas` in `docker-compose.prod.yml`) next to the old ones and waits until they are healthy. nginx resolves `backend` by itself (`server backend:8000 resolve`, `resolver 127.0.0.11 valid=5s`), so after `DEPLOY_DNS_SETTLE` (6 s) the old replicas are stopped (`docker stop -t 35`, graceful) and removed. If the new replicas do not become healthy within 180 s they are removed and the old ones keep serving: the deploy fails without a rollback because nothing else changed. Verified with Compose v5.5: `--no-recreate --scale` creates the missing replicas with the new configuration and leaves the existing ones alone. Requires the backend service without `container_name` (F0-04, `docker-compose.yml`). `DEPLOY_ROLLING=0` falls back to a plain `up -d --no-deps backend`, with about 5-10 s of 502 while the replicas are recreated.
7. The rest of the app: `up -d --no-deps --no-build --remove-orphans celery_worker celery_worker_interactive celery_beat frontend`. Compose only recreates what changed. The frontend container is recreated when its image changes (every release): the SPA answers 502 for a moment while it restarts. Accepted: the API keeps serving and the browser retries.
8. `nginx -t && nginx -s reload`. On a normal deploy the edge is only **reloaded**, never recreated or restarted; it re-resolves `backend` by itself.
9. Write `.deploy/current`.
10. **Gate** (60 s: 12 checks, 5 s apart):
    - `https://$DOMAIN/api/ops/health/ready` and `https://$DOMAIN/` answer 2xx; one failed check in total is tolerated.
    - No container of the project is `unhealthy`.
    - `rabbitmq-diagnostics -q alarms --formatter json` reports no alarm: with the pinned RabbitMQ 3.13.7 that is exactly `{"alarms":[],"node":"rabbit@...","result":"ok"}` (keys only `alarms`, `node` and `result`, each once, `alarms` empty). With alarms 3.13.7 prints another object (`local`, `global`, `message`) and still exits 0. Anything else, empty output, `[]` or unparseable output included, fails the gate; upgrading the RabbitMQ image means checking `alarms_command.ex` of the new tag and adjusting `rabbitmq_sin_alarmas` (a test pins the tag) (with a memory or disk alarm RabbitMQ blocks publishers: OTP and jobs stall while `/ready` still answers).
    - 5xx rate in the last 2 minutes of the nginx access log (`"s":"5..."`) under 0.5 %, counted only when there are at least 3 errors (one stray 502 on low traffic does not trigger a rollback).
11. Gate failed: **automatic rollback** (`DEPLOY_AUTO_ROLLBACK=1`), then exit 1. If the rollback's own gate also fails, the script alerts and exits 2: a person has to look.

Every step logs to stderr with a UTC timestamp. Failures send an alert through `ALERT_EMAIL`/`ALERT_WEBHOOK_URL`.

## 4. Rollback (`scripts/deploy.sh rollback`)

`APP_VERSION=$(cat .deploy/previous)`, then steps 4 and 6-10 **without migrating**. It does not rewrite `.deploy/previous`, so running it twice does not bounce between versions. Preflight skips the disk, backup and Quality checks: it is the emergency path, and it must work with GitHub down.

If the pull fails (GHCR down, token expired), the rollback continues with the local images, but only if every previous `image:tag` is still on the host. If one is missing it alerts and exits 2 without touching anything: there is nothing to roll back to, and a person decides.

## 4b. The edge (`make deploy-edge`)

nginx is recreated only by `scripts/deploy.sh edge`, and only when something changed: the id of its image (after `pull nginx`) differs from the running container's, or the sha256 of `nginx/nginx.prod.conf` differs from the one recorded in `.deploy/edge-conf.sha256` on the last run. A conf change needs a recreate, not just a reload: the conf is a single-file bind mount, and when `git pull` replaces the file the container keeps seeing the old inode. Recreating the edge drops every connection for a moment; do it outside peak hours. With nothing changed it only runs `nginx -t && nginx -s reload`.

Rollback is safe only because of the migration rule below: the previous release must work against the schema the new one migrated to.

Rolling back **below** the release that ships `e7a9c1d3f5b8` (service images uploaded to `store_media`, plan F1-28): the images keep being served by id and `services.image_url` stores an absolute `https` URL, which the previous release accepts. Only if that release cannot serve them (the media route changed) clear the links first, with the migration role:

```sql
UPDATE services SET image_url = NULL WHERE image_url LIKE '%/stores/media/%';
```

The rows stay in `store_media` (the downgrade never deletes images). A later upgrade links each one back to the service whose `image_url` still ends in `/stores/media/{id}`; if the links were cleared with the `UPDATE` above, those images have no service left and the upgrade stops with their count. Deleting them is a human decision: `DELETE FROM store_media WHERE kind = 'service' AND id NOT IN (SELECT substring(image_url FROM '/stores/media/([A-Za-z0-9_-]+)$') FROM services WHERE image_url IS NOT NULL);`

Rolling back **below** the release that ships `4b6d8f0a2c13` (PV-01, 2026-09-25: a client's email is unique per store, a login account's email stays globally unique): the migration drops the global unique on `users.email` in the same release that adds the partial uniques. That breaks expand/contract, and it is allowed only as a dated exception (section 5): this migration ships in the FIRST production release, Shifty has no live database, and the first deploy migrates an empty schema, so neither window exists yet. The older code DID rely on the global unique: its login and forgot-password look the account up by `email` alone with `scalar_one_or_none`. Both windows would break it: during a deploy (older code serving while the migration has already run) and after a `make rollback` without migrating. In either, a staff or admin account whose email a client also left (in any store) gets a 500 at login until the new release serves again. Neither window exists before the first release; after launch, a change like this ships in two releases. Before the rollback, list those accounts with the migration role and warn them:

```sql
SELECT u.email, u.store_id, u.role FROM users u
WHERE u.role <> 'client'
  AND EXISTS (SELECT 1 FROM users c WHERE c.email = u.email AND c.role = 'client');
```

`alembic downgrade` past `4b6d8f0a2c13` restores the global unique only if no email is in two rows; otherwise it stops with the count and changes nothing (it never picks which row keeps the email). The rows to fix by hand: `SELECT email, count(*) FROM users GROUP BY email HAVING count(*) > 1;`

## 5. Migrations: expand/contract

- A release only **adds** (expand): new nullable columns, new tables, new indexes. Code that stops using a column ships first; the migration that drops it (contract) ships in a **later** release.
- Indexes on live tables: `CREATE INDEX CONCURRENTLY` inside `op.get_context().autocommit_block()`, preceded by `DROP INDEX CONCURRENTLY IF EXISTS` (a failed concurrent build leaves an invalid index behind).
- Constraints: `NOT VALID` first, `VALIDATE CONSTRAINT` in a separate step.
- Backfills in batches, never one `UPDATE` over the whole table; no `ALTER TYPE` that rewrites a table.
- **Dated exception (2026-09-25), only one:** `4b6d8f0a2c13` (PV-01) drops the global unique on `users.email` in the same release that replaces it with the partial uniques. Allowed ONLY because it ships in the first production release (no live database, the first deploy starts from an empty schema, so there is no deploy window and no rollback window). After launch the rule applies without exceptions.
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

## 6. Staging: NOT on the production VPS

The production VPS has 8 GB (section 1): production's limits already take about 5.7 GiB steady and 6.7 GiB during a deploy, so a second full stack does not fit next to it. Running staging there would push the host into swap and the OOM killer, and the victim could be production's database. **Staging runs on another host** (a second, separate VPS, possibly a smaller or temporary one) **or locally** on a developer machine with the production view (`COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml`). Never on the production host, not even "just for a test".

The plan (plan §7, decision 29) described staging as a second compose project on the production VPS; that assumed a 16 GB host and no longer applies. Everything below still holds for a staging host of its own: there it is the only project, so it can keep the default ports and does not need the extra port override.

Staging is a clone, for example `/opt/shifty-staging`, with its own `.env`:

- `COMPOSE_PROJECT_NAME=shifty-staging`: containers, networks and volumes (the database included) are separate from production. Container names are `${COMPOSE_PROJECT_NAME:-shifty}_<service>` in the compose files, so the two projects do not collide (a fixed `container_name` would stop the second project from starting). The guard watches only its own project (`COMPOSE_PROJECT_NAME`).
- Its own secrets, `DOMAIN` and `BACKUP_DIR=/var/backups/shifty-staging` with `BACKUP_ALLOW_LOCAL_ONLY=1`, in its own ops file; point its scripts at it with `SHIFTY_OPS_ENV=/etc/shifty/ops-staging.env`.
- Only if staging ever shares a host with another project that publishes 80 and 443 does its nginx need other host ports (for example `127.0.0.1:8443:443`) through an extra override listed in its `COMPOSE_FILE`. That override does not exist; on a host of its own it is not needed.
- `docker-compose.prod.yml` fixes `ENV: production`, so without changes staging boots as production and needs the production-only requirements of section 1: Sentry, and Mercado Pago OAuth and webhook credentials from a non-`TEST-` app. A staging without real MP credentials needs `ENV: staging` in that same extra override (staging keeps the secret and MP API base checks, not the production ones). Its `.env` still has to define the MP and Sentry variables with some non-empty value: compose interpolates the `:?` of `docker-compose.prod.yml` before it applies any override.
- Deploy it with the same script: `APP_VERSION=<sha> DEPLOY_SKIP_BACKUP_CHECK=1 bash scripts/deploy.sh deploy` from its clone. An image built by hand from a branch (`workflow_dispatch`) has no green Quality on `main`; add `DEPLOY_SKIP_QUALITY_CHECK=1` for it (the deploy alerts that it skipped the check).
- The staging host needs the same 8 GB as production to run the production limits unchanged; on a smaller host, lower them in a staging-only override, never in `docker-compose.prod.yml`. Bring it up for a test and take it down afterwards (`docker compose down`, the volumes stay).

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
| NTP, TLS certificate, disk, per-container memory, host memory and swap, `redis_state` memory, host hardening, `docker stats` to `/var/log/shifty/stats.log` | hourly (cron) | `scripts/checks.sh` (runs `scripts/host-hardening-check.sh`) | NTP not synchronized, certificate < 20 days, disk > 80 % (critical > 90 %), container > 90 % of its memory limit, host `MemAvailable` under 10 % of RAM, no swap, or swap more than 50 % used; `redis_state` over 80 % of its `maxmemory` (`REDIS_STATE_MEM_MAX_PERCENT`), unreadable, or without `maxmemory`; any hardening step undone (section 1) or a reboot pending |
| Backup freshness | hourly (cron) | `scripts/backup-check.sh` | last successful backup > 26 h (critical > 48 h) |
| Latency and 5xx per route | every 5 min (cron) | `scripts/latency-check.sh` + `backend/scripts/latency_report.py` | a route with >= 20 requests over p95 500 ms or 5xx 0.1 %, or global 5xx over 0.1 % with >= 200 requests in the window |
| Top 20 queries of `pg_stat_statements` | Mondays 06:23 host time (cron; cron.d uses the host timezone) | `backend/scripts/pg_top_queries.py` inside the backend container | never: it is a report, read `/var/log/shifty/pg-top.log` |
| Daily backup | 03:00 ART (systemd timer) | `scripts/backup.sh` | any failure, or no `BACKUP_REMOTE` |
| Certificate renewal | certbot's own timer | `scripts/cert-deploy-hook.sh` | nginx did not reload after a renewal |

Repeated alerts are silenced for a while (30 minutes to 6 hours depending on the check) so a condition that lasts does not send a mail every minute. The guard does nothing while `.deploy/lock` exists.

**Weekly query report (plan F5-03).** `deploy/cron/shifty-pg-top` runs `docker compose exec -T backend python scripts/pg_top_queries.py` every Monday and appends to `/var/log/shifty/pg-top.log`: the 20 statements with the most total time and the 20 with the highest mean time, with calls, rows and their share of the total. It connects as the owner role (`BACKUP_DATABASE_URL` or `MIGRATION_DATABASE_URL`, never `DATABASE_URL`: under `shifty_app` the view hides other roles' query text) and prints the URL with the credentials masked; the query text is normalized by Postgres (`$1` instead of values), so it carries no customer data. Totals accumulate since the last reset, so compare week against week; to measure a single week run it by hand with `--reset` (it clears the stats after printing). By hand: `APP_VERSION=$(cat .deploy/current) docker compose exec -T backend python scripts/pg_top_queries.py --limit 20`.

**Sentry (plan F5-02).** With `SENTRY_DSN` set, traces are sampled per route (`backend/core/observability.py`): never `/ops/health/*` or `/ops/slo`, always `/payments/*` and the Mercado Pago webhook, 2 % of public GETs, 20 % of writes, 10 % of other panel reads; the release is `APP_VERSION`. Sentry Crons watches ONE beat task (owner decision 2026-09-25: stay on the free plan, which includes one cron monitor): `expire-unpaid-appointment-holds-every-minute`, because if it stops, appointments with an unpaid deposit are never released and the schedule stays taken. A run that keeps going but falls behind (Mercado Pago slow, many held charges) is a different signal: `oldest_overdue_hold_seconds` in `/ops/slo` (threshold `SLO_MAX_OLDEST_OVERDUE_HOLD_SECONDS`, 600 s), and the task itself reports an `OverdueHoldsLagging` event to Sentry over that threshold, at most once per 30 minutes per worker process. Charges the task parked because Mercado Pago reports them approved but they fail integrity are left out of that metric (each alerted once) and counted in `integrity_held_holds`, with no count threshold: a non-zero value is a paid appointment stuck in `pending_payment` that needs a person. Once a parked charge becomes eligible for its hourly recheck, `oldest_due_held_recheck_seconds` counts only the delay after that recheck was due. The separate threshold `SLO_MAX_OLDEST_DUE_HELD_RECHECK_SECONDS` defaults to 900 s (allowed 60-3600 s); `/ops/slo` emits `held_recheck_lag_high`, and the job reports `HeldRecheckLagging` to Sentry at most once per 30 minutes per worker process. Re-parking after a recheck resets that timer; this alert does not count the hour during which the charge is intentionally parked. `exclude_beat_tasks` in the `CeleryIntegration` excludes every other beat entry with one regex (`SENTRY_CRONS_EXCLUDED_BEAT_TASKS` in `core/observability.py`), so a new beat task is born without a monitor and never exceeds the quota. The other seven crontab tasks and the outbox (every 20 s; Sentry skips intervals under 60 s anyway) are covered by `/ops/slo` (`oldest_pending_outbox_seconds`, `oldest_pending_email_send_seconds`, pending and failed webhooks) and by the worker heartbeat healthcheck. Monitoring more tasks means a paid cron quota: change the regex and this paragraph together. **One-time cleanup:** in any Sentry project (environment) that ran F5-02 before this change, the other seven crontab tasks already created cron monitors (`process-payment-webhook-inbox-every-minute`, `reconcile-pending-payments-every-2-minutes`, `process-appointment-reminders-every-15-minutes`, `process-waitlist-offers-every-minute`, `purge-expired-auth-sessions-daily`, `purge-expired-data-daily`, `process-subscription-lifecycle-daily`). They no longer get check-ins, so Sentry marks them missed and keeps counting them against the quota: delete them by hand in Sentry (Crons, each monitor, Delete) after deploying this change. Keep only `expire-unpaid-appointment-holds-every-minute`.

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
- **"Quality no paso en main para <sha>"**: that commit's `Quality` run on `main` failed or is still running, the sha is short (it must be the full 40 characters), or the image was built by hand from a branch. Deploy a sha whose Quality is green; there is no `Build images` run without one.
- **"no pude preguntarle a GitHub"**: api.github.com did not answer; without `DEPLOY_GITHUB_TOKEN` the private repository answers 404 (set the token, section 3); with it, the token expired or lacks "Actions: read" on this repository; on a public repository without a token, the unauthenticated rate limit (60 per hour per IP) ran out. Retry later; if it is urgent, check the commit's Quality run in Actions by hand and deploy with `DEPLOY_SKIP_QUALITY_CHECK=1` (it alerts).
- **"redis_state: usa el N % de su maxmemory"**: `redis_state` holds rate limits, idempotency keys, OTP codes, lockouts, OAuth state and Celery results with `noeviction`; at 100 % every write fails and auth, OTP and the public booking answer 503. Find what grew: `APP_VERSION=$(cat .deploy/current) docker compose exec redis_state redis-cli --bigkeys` and `... redis-cli INFO keyspace` (database 1 is the Celery result backend). Never switch it to an evicting policy or flush it to "fix" it: an eviction silently drops protections (CLAUDE.md, "Dos Redis con papeles distintos"). Raising `--maxmemory` in `docker-compose.yml` means raising its 96M container limit too and redoing the memory budget of section 1.
- **Manual compose commands** need the version (the prod compose file refuses to interpolate without it): `APP_VERSION=$(cat .deploy/current) docker compose ps`.
- **First deploy with this script**: `.deploy/previous` comes from the tag of the running backend image. If that is `latest` or a local build, there is nothing to roll back to; say so in the release notes.
- **The gate failed but the release is fine** (for example the domain's DNS or certificate): fix the cause and deploy the same sha again; migrations are idempotent at head.
