# Migrate VPS deployment to signaled CI/CD

## Overview

- Replace the current production deployment model, where a local machine rsyncs files into `/opt/my_tg_bot`, with a signaled CI/CD model:
  - GitHub Actions connects to the VPS as `cicd`.
  - `cicd` can only start/status one deploy systemd unit.
  - the VPS pulls `main` from GitHub using its own read-only deploy key.
  - Docker Compose rebuilds/restarts the bot on the VPS.
- Keep direct local deployment from `~/src/my_tg_bot`, but make it an intentional temporary replacement of the production container instead of a second coexisting bot.
- Move production runtime files to FHS-style locations:
  - production checkout: `/srv/my_tg_bot/app`
  - production data: `/var/lib/my_tg_bot/data`
  - production env file: `/etc/my_tg_bot/my_tg_bot.env`
  - deploy script: `/usr/local/sbin/deploy-my-tg-bot`
  - systemd units: `/etc/systemd/system/my-tg-bot.service` and `/etc/systemd/system/my-tg-bot-deploy.service`
- Store systemd unit files and deploy scripts in this repo as source-controlled templates, even though production uses the copies installed under `/etc/systemd/system` and `/usr/local/sbin`.
- Expected result:
  - pushes to `main` run tests and then trigger production deployment through GitHub Actions.
  - production secrets are never stored in GitHub Actions.
  - GitHub Actions cannot directly read or modify production files on the VPS.
  - the existing SQLite data is preserved.
  - `scripts/deploy.sh` remains available for temporary manual test deployments that replace the active production container until the deploy service restores `main`.
  - direct-push deployment risk is explicitly accepted for this private bot; for now, no branch protection is required.

## Implementation Status

Completed on 2026-05-26:

- [x] made Docker Compose configurable for env file, data path, image tag, and runtime UID/GID.
- [x] added container hardening in Compose (`no-new-privileges`, `cap_drop: ALL`, `/tmp` tmpfs).
- [x] updated Docker runtime env for non-root execution (`HOME=/tmp`, `XDG_CACHE_HOME=/tmp/.cache`).
- [x] added repo-owned deploy assets under `deploy/`:
  - [x] `deploy/systemd/my-tg-bot.service`
  - [x] `deploy/systemd/my-tg-bot-deploy.service`
  - [x] `deploy/scripts/deploy-my-tg-bot`
  - [x] `deploy/sudoers/cicd-my-tg-bot`
- [x] updated `scripts/deploy.sh` to do root/admin manual replacement deployment of the active stack.
- [x] added GitHub Actions workflow at `.github/workflows/deploy.yml`.
- [x] rewrote `docs/deploy.md` for CI/CD production deployment, manual replacement deployment, validation, and rollback.
- [x] bootstrapped VPS directories, env/data migration, GitHub host key trust, installed systemd/deploy/sudoers files.
- [x] validated GitHub deploy key access to `mjh-sakh/my_tg_bot` from the VPS.
- [x] validated `cicd` limited sudo access and confirmed `cicd` cannot read `/etc/my_tg_bot/my_tg_bot.env`.
- [x] stopped legacy `/opt/my_tg_bot` Compose stack and started the new `/srv/my_tg_bot/app` stack through manual replacement deployment.
- [x] validated the running container uses UID `101`, GID `104`, and `/var/lib/my_tg_bot/data` contains `bot.sqlite`.
- [x] ran local validation:
  - [x] `bash -n scripts/deploy.sh deploy/scripts/deploy-my-tg-bot`
  - [x] `docker compose config`
  - [x] `direnv exec . uv run pytest` (`56 passed, 1 skipped`)

Remaining follow-up:

- [ ] commit and push these repo changes to `main`; until then, `my-tg-bot-deploy.service` will reset the VPS checkout back to the previous `main` revision.
- [ ] after pushing, trigger GitHub Actions or manually run `sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service` to verify the pull-based release path end to end.
- [ ] manually verify Telegram bot behavior (`/start`, `/whoami`, chat, voice) after the pushed release deploy.

## Context

### Existing repository deployment files

- `docs/deploy.md`
  - documents the current rsync-based deployment to `/opt/my_tg_bot`.
- `scripts/deploy.sh`
  - rsyncs selected files from the local checkout to the VPS.
  - uploads local `.env` to the VPS.
  - runs `docker compose up -d --build --remove-orphans` on the VPS.
- `docker-compose.yml`
  - defines one service, `bot`.
  - currently hardcodes `/opt/my_tg_bot/data:/app/data`.
  - currently reads app secrets from `.env` in the compose directory.
- `Dockerfile`
  - builds a Python 3.13 runtime image.
  - runs `python -m bot.main`.
- `.dockerignore`
  - already excludes local secrets, tests, docs, and tooling from Docker build context.
- `.github/workflows/`
  - currently absent.

### Existing app runtime shape

- The bot stores SQLite data at `/app/data/bot.sqlite` inside the container.
- In production today, `/opt/my_tg_bot/data` is bind-mounted to `/app/data`.
- `bot/clients/sqlite_client.py` creates the data directory if needed.
- `bot/main.py` reads secrets and settings from process environment variables.
- Required production environment variables include at least:
  - `TELEGRAM_TOKEN`
  - `OPENROUTER_KEY`
  - `TOGETHER_API_KEY`
  - `ADMIN_ID`

### Current VPS state discovered during setup

- Current app path: `/opt/my_tg_bot`.
- `/opt/my_tg_bot` is not a git checkout.
- Current container is running through Docker Compose:
  - service: `bot`
  - image: `my-tg-bot:latest`
  - container name shape: `my_tg_bot-bot-1`
- Current ownership is mixed from prior deployments:
  - `/opt/my_tg_bot` mostly `501:staff`
  - `/opt/my_tg_bot/.env` is `root:root 600`
  - `/opt/my_tg_bot/data` is `root:root 700`
  - `/opt/my_tg_bot/data/bot.sqlite` is `root:root`
- Docker, Docker Compose, and Git are installed on the VPS.

### Already-created VPS deploy identities

- `cicd`
  - SSH-capable user for GitHub Actions signaling.
  - public key for GitHub Actions SSH access is installed in `/home/cicd/.ssh/authorized_keys`.
  - GitHub Actions repo secrets already created:
    - `VPS_HOST`
    - `VPS_PORT`
    - `VPS_USER`
    - `VPS_SSH_KEY`
    - `VPS_KNOWN_HOSTS`
- `tg-bot`
  - system runtime identity with no login shell.
  - current UID/GID on the VPS:
    - UID: `101`
    - GID: `104`
  - for Docker Compose, this user will be used as the numeric container runtime UID/GID and as owner of the host data directory.
- GitHub repo deploy key for VPS pulls:
  - private key: `/etc/ssh/deploy-keys/tg-bot_github`
  - public key: `/etc/ssh/deploy-keys/tg-bot_github.pub`
  - public key must be added to `mjh-sakh/my_tg_bot` as a read-only deploy key.

## Chosen Approach

### Production deployment

Use a pull-based production deploy:

```text
GitHub push to main
  -> GitHub Actions tests the repo
  -> GitHub Actions SSHes as cicd
  -> cicd starts my-tg-bot-deploy.service via limited sudo
  -> root-owned deploy script fetches/resets /srv/my_tg_bot/app to origin/main
  -> my-tg-bot.service rebuilds/restarts Docker Compose
  -> bot container runs as tg-bot UID/GID and uses /var/lib/my_tg_bot/data
```

Production files on the VPS:

```text
/srv/my_tg_bot/app                         git checkout of main
/var/lib/my_tg_bot/data                    persistent SQLite data, owned by tg-bot:tg-bot
/etc/my_tg_bot/my_tg_bot.env               production app secrets, root:root 600
/etc/ssh/deploy-keys/tg-bot_github         read-only GitHub deploy key, root:root 600
/usr/local/sbin/deploy-my-tg-bot           installed copy of repo deploy script, root:root 755
/etc/systemd/system/my-tg-bot.service      installed copy of repo systemd unit
/etc/systemd/system/my-tg-bot-deploy.service installed copy of repo systemd unit
/etc/sudoers.d/cicd-my-tg-bot              limited sudoers rule for cicd
```

Production systemd responsibilities:

- `my-tg-bot.service`
  - controls the Docker Compose app stack.
  - runs Docker commands as root because Docker management is privileged.
  - starts the container with numeric user `101:104` so the app process does not run as root inside the container.
  - points Compose to `/etc/my_tg_bot/my_tg_bot.env` and `/var/lib/my_tg_bot/data`.
  - uses `docker compose up -d`, so systemd controls start/stop/restart commands while Docker Compose and Docker restart policy supervise the running container.
- `my-tg-bot-deploy.service`
  - one-shot deploy unit.
  - runs `/usr/local/sbin/deploy-my-tg-bot` as root.
  - performs git fetch/reset and restarts `my-tg-bot.service`.

### Direct manual replacement deployment

Keep direct local deployment, but make it an intentional temporary replacement of the active production stack. Manual deployment is an administrator operation and uses the existing root SSH access, not the restricted `cicd` user:

```text
local checkout -> scripts/deploy.sh -> SSH as root/netcup -> rsync selected files to /srv/my_tg_bot/app -> docker compose down/up for project my_tg_bot
```

Default manual replacement paths:

```text
/srv/my_tg_bot/app
/var/lib/my_tg_bot/data
/etc/my_tg_bot/my_tg_bot.env
```

Only one Telegram long-polling bot should run for the production token. The manual deploy therefore uses the same Compose project (`my_tg_bot`) and same data/env locations as production. It stops/recreates the active container with the locally rsynced code. A later manual or CI-triggered start of `my-tg-bot-deploy.service` resets `/srv/my_tg_bot/app` back to `origin/main`, rebuilds, and swaps the running container back to the production release.

The direct deploy must preserve the git checkout metadata in `/srv/my_tg_bot/app` so the deploy service can recover cleanly with `git reset --hard origin/main` and `git clean -fdx`. Because it uses root SSH, it can write to the root-owned checkout, read `/etc/my_tg_bot/my_tg_bot.env`, and manage Docker directly. This root access is for manual administrator deployment only and is not stored in GitHub Actions.

### Rejected alternatives

- Keep production as rsync from GitHub Actions.
  - rejected because it would place more deployment power and potentially secrets-adjacent behavior in GitHub Actions.
- Let `cicd` run `git pull` and `docker compose` directly.
  - rejected because `cicd` would need broad access to production files and Docker privileges.
- Switch away from Docker to a direct Python systemd service.
  - rejected because the current project already has a simple working Docker Compose deployment and the user explicitly called out Docker-related changes.
- Run production and direct-test deployments as separate coexisting Compose projects.
  - rejected because the bot uses Telegram long polling and two containers using the same production token can conflict; the simpler intended behavior is one active bot container that manual deployment can temporarily replace.
- Use `/opt/my_tg_bot` as the new production path.
  - rejected because the migration is an opportunity to move production state into clearer standard locations and leave the old path available for rollback until verification is complete.

## Development Approach

- testing approach: implementation-first with validation after each logical unit.
- keep production CI/CD and direct manual deploy as two ways to control the same active stack, not two coexisting stacks.
- keep systemd/deploy files source-controlled under `deploy/`, then install copies to VPS system locations.
- avoid introducing a general deployment framework; use simple shell scripts, systemd, Docker Compose, and GitHub Actions.
- keep app code changes minimal; this is mostly deployment infrastructure.
- update this plan as tasks complete or if exact VPS paths change.

## Testing Strategy

### Local validation

Run from the repo root:

```bash
mise exec -- direnv exec . uv run pytest
```

Validate Docker Compose config locally:

```bash
docker compose config
```

If Docker is available locally, optionally validate build:

```bash
docker compose build
```

### VPS validation

Validate GitHub host key trust for non-interactive VPS pulls:

```bash
ssh-keygen -F github.com -f /etc/ssh/ssh_known_hosts
```

Validate deploy key can read the repo:

```bash
GIT_SSH_COMMAND='ssh -i /etc/ssh/deploy-keys/tg-bot_github -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ssh/ssh_known_hosts -o StrictHostKeyChecking=yes' \
  git ls-remote git@github.com:mjh-sakh/my_tg_bot.git HEAD
```

Validate systemd files:

```bash
systemd-analyze verify /etc/systemd/system/my-tg-bot.service
systemd-analyze verify /etc/systemd/system/my-tg-bot-deploy.service
```

Validate production deploy manually:

```bash
sudo systemctl daemon-reload
sudo systemctl start my-tg-bot-deploy.service
sudo systemctl status --no-pager my-tg-bot-deploy.service
sudo systemctl status --no-pager my-tg-bot.service
cd /srv/my_tg_bot/app && docker compose ps
```

Validate GitHub Actions signaling:

```bash
ssh cicd@<vps> 'sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service && sudo -n /usr/bin/systemctl status --no-pager my-tg-bot-deploy.service'
```

Validate runtime behavior:

- bot responds to `/start`.
- bot responds to `/whoami`.
- existing authorization data remains present after migration.
- one `/chat` request works.
- one voice transcription works if credentials are available.
- restarting/recreating the container preserves `/var/lib/my_tg_bot/data/bot.sqlite`.

## Progress Tracking

- mark completed work with `[x]`.
- use `[ ]` for pending work.
- add `➕` for newly discovered work.
- add `⚠️` for blockers, risks, or open decisions.

## Implementation Steps

### Task 1: Make Docker Compose path- and environment-configurable

**Files:**

- Modify: `docker-compose.yml`
- Modify: `Dockerfile`
- Modify if needed: `.dockerignore`

- [ ] replace the hardcoded host data mount `/opt/my_tg_bot/data:/app/data` with a variable such as `${MY_TG_BOT_DATA_DIR:-./data}:/app/data`.
- [ ] replace the hardcoded compose env file `.env` with a variable such as `${MY_TG_BOT_ENV_FILE:-.env}`.
- [ ] set the container runtime user through Compose using `${MY_TG_BOT_UID:-1000}:${MY_TG_BOT_GID:-1000}`.
- [ ] add conservative container hardening where compatible:
  - [ ] `security_opt: ["no-new-privileges:true"]`
  - [ ] `cap_drop: ["ALL"]`
  - [ ] consider `tmpfs: ["/tmp"]` if runtime libraries need temporary writable space.
- [ ] keep the image name compatible with current usage, e.g. `${MY_TG_BOT_IMAGE:-my-tg-bot:latest}`.
- [ ] ensure the Dockerfile/runtime image does not require writing to `/app` at runtime.
- [ ] set runtime cache/temp env vars if needed, for example `HOME=/tmp` and `XDG_CACHE_HOME=/tmp/.cache`.
- [ ] run `mise exec -- direnv exec . uv run pytest`.
- [ ] run `docker compose config` and confirm default local values still produce a valid Compose config.

### Task 2: Add source-controlled production deploy assets

**Files:**

- Create: `deploy/systemd/my-tg-bot.service`
- Create: `deploy/systemd/my-tg-bot-deploy.service`
- Create: `deploy/scripts/deploy-my-tg-bot`
- Create: `deploy/sudoers/cicd-my-tg-bot`

- [ ] create `deploy/systemd/my-tg-bot.service` as the source-controlled unit for the Docker Compose stack.
- [ ] configure `my-tg-bot.service` with:
  - [ ] `WorkingDirectory=/srv/my_tg_bot/app`
  - [ ] `Environment=COMPOSE_PROJECT_NAME=my_tg_bot`
  - [ ] `Environment=MY_TG_BOT_ENV_FILE=/etc/my_tg_bot/my_tg_bot.env`
  - [ ] `Environment=MY_TG_BOT_DATA_DIR=/var/lib/my_tg_bot/data`
  - [ ] `Environment=MY_TG_BOT_UID=101`
  - [ ] `Environment=MY_TG_BOT_GID=104`
  - [ ] `ExecStart=/usr/bin/docker compose up -d --build --remove-orphans`
  - [ ] `ExecStop=/usr/bin/docker compose down`
  - [ ] `Type=oneshot` and `RemainAfterExit=yes`.
- [ ] create `deploy/systemd/my-tg-bot-deploy.service` as a one-shot unit that runs `/usr/local/sbin/deploy-my-tg-bot`.
- [ ] configure `my-tg-bot-deploy.service` with:
  - [ ] `After=network-online.target docker.service`
  - [ ] `Wants=network-online.target`
  - [ ] `Requires=docker.service`
  - [ ] `Type=oneshot`
  - [ ] `User=root`
  - [ ] `TimeoutStartSec=900`
  - [ ] `ExecStart=/usr/local/sbin/deploy-my-tg-bot`.
- [ ] create `deploy/scripts/deploy-my-tg-bot` with:
  - [ ] `set -euo pipefail`.
  - [ ] constants for repo URL, branch, app dir, deploy key, data dir, and env file.
  - [ ] directory creation for `/srv/my_tg_bot/app`, `/var/lib/my_tg_bot/data`, and `/etc/my_tg_bot`.
  - [ ] ownership/permissions for `/var/lib/my_tg_bot/data` as `tg-bot:tg-bot` with restrictive mode.
  - [ ] a guard that fails clearly if `/etc/my_tg_bot/my_tg_bot.env` is missing.
  - [ ] a guard that fails clearly if `/etc/ssh/deploy-keys/tg-bot_github` is missing.
  - [ ] clone if `/srv/my_tg_bot/app/.git` is absent.
  - [ ] fetch/reset to `origin/main` if checkout already exists.
  - [ ] `git clean -fdx` only after confirming the target is the expected app checkout.
  - [ ] restart `my-tg-bot.service` through `/usr/bin/systemctl restart my-tg-bot.service`.
- [ ] confirm the VPS `systemctl` path with `command -v systemctl` and use that exact path in the sudoers file and GitHub Actions workflow.
- [ ] create `deploy/sudoers/cicd-my-tg-bot` allowing only these exact commands, assuming `/usr/bin/systemctl` on Debian:
  - [ ] `/usr/bin/systemctl start my-tg-bot-deploy.service`
  - [ ] `/usr/bin/systemctl status --no-pager my-tg-bot-deploy.service`
  - [ ] optionally `/usr/bin/systemctl status --no-pager my-tg-bot.service`.
- [ ] ensure all CI and manual `cicd` examples use `sudo -n` so permission mistakes fail fast instead of waiting for a password prompt.
- [ ] run shell syntax validation for the deploy script:
  - [ ] `bash -n deploy/scripts/deploy-my-tg-bot`.

### Task 3: Update direct local deploy as a manual replacement deployment

**Files:**

- Modify: `scripts/deploy.sh`
- Modify: `docs/deploy.md`

- [ ] change `scripts/deploy.sh` defaults so direct deployment targets the same active production stack, not a separate test stack:
  - [ ] `REMOTE_HOST=${REMOTE_HOST:-netcup}`
  - [ ] `REMOTE_DIR=${REMOTE_DIR:-/srv/my_tg_bot/app}`
  - [ ] `REMOTE_DATA_DIR=${REMOTE_DATA_DIR:-/var/lib/my_tg_bot/data}`
  - [ ] `REMOTE_ENV_FILE=${REMOTE_ENV_FILE:-/etc/my_tg_bot/my_tg_bot.env}`
  - [ ] `COMPOSE_PROJECT_NAME=${COMPOSE_PROJECT_NAME:-my_tg_bot}`
  - [ ] `MY_TG_BOT_IMAGE=${MY_TG_BOT_IMAGE:-my-tg-bot:manual}`.
- [ ] keep the existing focused rsync include/exclude behavior for application files.
- [ ] ensure rsync does not delete or replace `.git/` in `/srv/my_tg_bot/app`; the production deploy service must be able to reset the checkout back to `origin/main`.
- [ ] specify safe rsync semantics for writing into a git checkout:
  - [ ] keep `--delete` limited to the selected application file set.
  - [ ] explicitly exclude `.git/`, `.gitignore`, `.env`, data directories, and deploy-only server files from deletion/replacement.
  - [ ] preserve the current include-only pattern for runtime files (`Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `uv.lock`, `bot/**`).
- [ ] after manual rsync, validate checkout recoverability:

```bash
test -d /srv/my_tg_bot/app/.git
git -C /srv/my_tg_bot/app remote get-url origin
git -C /srv/my_tg_bot/app status --short
```
- [ ] stop/recreate the active Compose project rather than starting a second bot:
  - [ ] `docker compose down`
  - [ ] `docker compose up -d --build --remove-orphans`
- [ ] do not upload local `.env` by default; direct manual replacement should use the server env file at `/etc/my_tg_bot/my_tg_bot.env`.
- [ ] allow an explicit override for `REMOTE_ENV_FILE` only when intentionally testing against a different server-side env file.
- [ ] set Compose environment variables explicitly when running remote Docker Compose:
  - [ ] `COMPOSE_PROJECT_NAME`
  - [ ] `MY_TG_BOT_DATA_DIR`
  - [ ] `MY_TG_BOT_ENV_FILE`
  - [ ] `MY_TG_BOT_IMAGE`
  - [ ] `MY_TG_BOT_UID`
  - [ ] `MY_TG_BOT_GID`.
- [ ] ensure the shared data directory is writable by the container UID/GID:
  - [ ] create `${REMOTE_DATA_DIR}` if missing.
  - [ ] run `chown ${MY_TG_BOT_UID}:${MY_TG_BOT_GID} ${REMOTE_DATA_DIR}` when the SSH user has permission.
  - [ ] otherwise fail with a clear message explaining the required one-time root bootstrap.
- [ ] reuse `tg-bot` UID/GID (`101:104`) for manual replacement deployments on the same VPS.
- [ ] update `docs/deploy.md` so production CI/CD and direct manual replacement are separate procedures for the same active stack.
- [ ] include examples for manual replacement and restoration:

```bash
./scripts/deploy.sh
ssh netcup 'sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service'
```

- [ ] validate the script locally with `bash -n scripts/deploy.sh`.
- [ ] validate production-equivalent Compose config on the VPS:

```bash
cd /srv/my_tg_bot/app
COMPOSE_PROJECT_NAME=my_tg_bot \
MY_TG_BOT_IMAGE=my-tg-bot:latest \
MY_TG_BOT_ENV_FILE=/etc/my_tg_bot/my_tg_bot.env \
MY_TG_BOT_DATA_DIR=/var/lib/my_tg_bot/data \
MY_TG_BOT_UID=101 \
MY_TG_BOT_GID=104 \
docker compose config
```

### Task 4: Add GitHub Actions workflow for release deployment

**Files:**

- Create: `.github/workflows/deploy.yml`
- Modify if needed: `README.md`
- Modify if needed: `docs/deploy.md`

- [ ] create a workflow triggered by:
  - [ ] push to `main`.
  - [ ] `workflow_dispatch` for manual release redeploys.
- [ ] add a test job that:
  - [ ] checks out the repo.
  - [ ] sets up Python 3.13.
  - [ ] installs `uv`.
  - [ ] runs `uv sync --frozen --dev`.
  - [ ] runs `uv run pytest`.
- [ ] add a deploy job that depends on tests.
- [ ] document the current `main` policy explicitly:
  - [ ] for now, no branch protection is required.
  - [ ] direct push to `main` deploys production and this risk is accepted for this private bot.
  - [ ] revisit required PRs/status checks/restricted pushes if repository access broadens.
- [ ] make the deploy job use GitHub Actions environment `production` if manual approval is desired.
- [ ] install the SSH private key from `secrets.VPS_SSH_KEY` into the runner with mode `600`.
- [ ] write `secrets.VPS_KNOWN_HOSTS` into `~/.ssh/known_hosts`.
- [ ] SSH to the VPS using:

```bash
ssh -p "${{ secrets.VPS_PORT }}" \
  "${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }}" \
  'sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service && sudo -n /usr/bin/systemctl status --no-pager my-tg-bot-deploy.service'
```

- [ ] keep production secrets out of GitHub Actions; do not add Telegram/API tokens to repo secrets.
- [ ] add workflow timeout protection, e.g. `timeout-minutes: 20` for deploy.
- [ ] validate workflow syntax by pushing to a branch or using `gh workflow`/GitHub UI after merge.

### Task 5: Update production deployment documentation

**Files:**

- Modify: `docs/deploy.md`
- Modify if needed: `README.md`

- [ ] rewrite `docs/deploy.md` around the new split:
  - [ ] production CI/CD deployment.
  - [ ] direct local manual replacement deployment.
  - [ ] restoring `main` after a manual replacement by starting `my-tg-bot-deploy.service`.
  - [ ] VPS bootstrap/install procedure.
  - [ ] rollback notes.
  - [ ] status/log commands.
- [ ] document production paths:
  - [ ] `/srv/my_tg_bot/app`
  - [ ] `/var/lib/my_tg_bot/data`
  - [ ] `/etc/my_tg_bot/my_tg_bot.env`
  - [ ] `/usr/local/sbin/deploy-my-tg-bot`
  - [ ] `/etc/systemd/system/my-tg-bot.service`
  - [ ] `/etc/systemd/system/my-tg-bot-deploy.service`.
- [ ] document GitHub prerequisites:
  - [ ] `VPS_HOST`
  - [ ] `VPS_PORT`
  - [ ] `VPS_USER`
  - [ ] `VPS_SSH_KEY`
  - [ ] `VPS_KNOWN_HOSTS`
  - [ ] read-only repo deploy key installed on the VPS and added to GitHub repo deploy keys.
- [ ] document production status commands:

```bash
sudo systemctl status --no-pager my-tg-bot.service
sudo systemctl status --no-pager my-tg-bot-deploy.service
sudo journalctl -u my-tg-bot.service -n 100 --no-pager
sudo journalctl -u my-tg-bot-deploy.service -n 100 --no-pager
cd /srv/my_tg_bot/app && docker compose ps
```

- [ ] document manual replacement status commands with `COMPOSE_PROJECT_NAME=my_tg_bot` and note that only one bot container should be active.
- [ ] document that `/opt/my_tg_bot` is legacy after migration and should be retained until production verification is complete.

### Task 6: Bootstrap the VPS production directories and secret locations

**Files:**

- No repo file changes expected after documentation is complete.
- VPS changes:
  - `/srv/my_tg_bot/app`
  - `/var/lib/my_tg_bot/data`
  - `/etc/my_tg_bot/my_tg_bot.env`

- [ ] stop the current legacy container only when ready for cutover:

```bash
cd /opt/my_tg_bot && docker compose down
```

- [ ] create production directories:

```bash
install -d -m 755 -o root -g root /srv/my_tg_bot
install -d -m 755 -o root -g root /srv/my_tg_bot/app
install -d -m 750 -o tg-bot -g tg-bot /var/lib/my_tg_bot/data
install -d -m 700 -o root -g root /etc/my_tg_bot
install -d -m 700 -o root -g root /etc/ssh/deploy-keys
```

- [ ] copy current production env file:

```bash
install -m 600 -o root -g root /opt/my_tg_bot/.env /etc/my_tg_bot/my_tg_bot.env
```

- [ ] copy current SQLite data:

```bash
rsync -a /opt/my_tg_bot/data/ /var/lib/my_tg_bot/data/
chown -R tg-bot:tg-bot /var/lib/my_tg_bot/data
chmod 750 /var/lib/my_tg_bot/data
chmod 640 /var/lib/my_tg_bot/data/bot.sqlite
```

- [ ] keep `/opt/my_tg_bot` unchanged as rollback source until the new deployment is verified.
- [ ] validate that `/etc/my_tg_bot/my_tg_bot.env` is not readable by `cicd`.
- [ ] validate that `/var/lib/my_tg_bot/data/bot.sqlite` is not readable by `cicd` unless intentionally granted.
- [ ] install or verify GitHub SSH host key trust for non-interactive root/systemd pulls:

```bash
ssh-keyscan github.com > /tmp/github_known_hosts
# Verify fingerprints against GitHub's published SSH key fingerprints before installing.
install -m 644 -o root -g root /tmp/github_known_hosts /etc/ssh/ssh_known_hosts
ssh-keygen -F github.com -f /etc/ssh/ssh_known_hosts
rm -f /tmp/github_known_hosts
```

### Task 7: Install repo-owned deploy assets onto the VPS

**Files:**

- Source-controlled files from Task 2.
- VPS install targets:
  - `/usr/local/sbin/deploy-my-tg-bot`
  - `/etc/systemd/system/my-tg-bot.service`
  - `/etc/systemd/system/my-tg-bot-deploy.service`
  - `/etc/sudoers.d/cicd-my-tg-bot`

- [ ] copy `deploy/scripts/deploy-my-tg-bot` to `/usr/local/sbin/deploy-my-tg-bot`.
- [ ] set ownership and permissions:

```bash
chown root:root /usr/local/sbin/deploy-my-tg-bot
chmod 755 /usr/local/sbin/deploy-my-tg-bot
```

- [ ] copy systemd units:

```bash
cp deploy/systemd/my-tg-bot.service /etc/systemd/system/my-tg-bot.service
cp deploy/systemd/my-tg-bot-deploy.service /etc/systemd/system/my-tg-bot-deploy.service
chown root:root /etc/systemd/system/my-tg-bot.service /etc/systemd/system/my-tg-bot-deploy.service
chmod 644 /etc/systemd/system/my-tg-bot.service /etc/systemd/system/my-tg-bot-deploy.service
```

- [ ] copy sudoers rule:

```bash
cp deploy/sudoers/cicd-my-tg-bot /etc/sudoers.d/cicd-my-tg-bot
chown root:root /etc/sudoers.d/cicd-my-tg-bot
chmod 440 /etc/sudoers.d/cicd-my-tg-bot
visudo -cf /etc/sudoers.d/cicd-my-tg-bot
```

- [ ] reload systemd:

```bash
systemctl daemon-reload
```

- [ ] verify systemd units:

```bash
systemd-analyze verify /etc/systemd/system/my-tg-bot.service
systemd-analyze verify /etc/systemd/system/my-tg-bot-deploy.service
```

### Task 8: Validate GitHub deploy key and first production deploy

**Files:**

- No repo file changes expected.
- VPS state changes expected under `/srv/my_tg_bot/app`.

- [ ] confirm the read-only deploy key has been added to GitHub repo deploy keys.
- [ ] validate repo access from VPS:

```bash
GIT_SSH_COMMAND='ssh -i /etc/ssh/deploy-keys/tg-bot_github -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ssh/ssh_known_hosts -o StrictHostKeyChecking=yes' \
  git ls-remote git@github.com:mjh-sakh/my_tg_bot.git refs/heads/main
```

- [ ] start the production deploy service manually as root:

```bash
sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service
```

- [ ] verify deploy service result:

```bash
sudo systemctl status --no-pager my-tg-bot-deploy.service
sudo journalctl -u my-tg-bot-deploy.service -n 200 --no-pager
```

- [ ] verify app service result:

```bash
sudo systemctl status --no-pager my-tg-bot.service
cd /srv/my_tg_bot/app && docker compose ps
```

- [ ] verify the checkout is on `main` and clean:

```bash
cd /srv/my_tg_bot/app
git branch --show-current
git status --short
git rev-parse HEAD
```

- [ ] verify production-equivalent Compose config:

```bash
cd /srv/my_tg_bot/app
COMPOSE_PROJECT_NAME=my_tg_bot \
MY_TG_BOT_IMAGE=my-tg-bot:latest \
MY_TG_BOT_ENV_FILE=/etc/my_tg_bot/my_tg_bot.env \
MY_TG_BOT_DATA_DIR=/var/lib/my_tg_bot/data \
MY_TG_BOT_UID=101 \
MY_TG_BOT_GID=104 \
docker compose config
```

- [ ] verify container runtime UID/GID:

```bash
cd /srv/my_tg_bot/app
docker compose exec bot id
```

Expected: UID `101`, GID `104`.

- [ ] verify exactly one bot container is active for the production token:

```bash
docker ps --filter 'name=my_tg_bot' --format '{{.Names}} {{.Status}}'
```

- [ ] inspect the active container mounts and confirm `/var/lib/my_tg_bot/data` is mounted at `/app/data`.
- [ ] verify SQLite file exists and remains under `/var/lib/my_tg_bot/data`.
- [ ] manually test Telegram commands.

### Task 9: Validate limited `cicd` signaling and GitHub Actions deployment

**Files:**

- `.github/workflows/deploy.yml` from Task 4.

- [ ] from a local machine or root session, verify `cicd` can only start/status intended services:

```bash
ssh cicd@<vps> 'sudo -l'
ssh cicd@<vps> 'sudo -n /usr/bin/systemctl status --no-pager my-tg-bot-deploy.service'
ssh cicd@<vps> 'sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service'
```

- [ ] verify `cicd` cannot read production secrets:

```bash
ssh cicd@<vps> 'cat /etc/my_tg_bot/my_tg_bot.env'
```

Expected: permission denied.

- [ ] verify `cicd` cannot directly modify production checkout or data.
- [ ] trigger `workflow_dispatch` from GitHub Actions.
- [ ] verify the workflow runs tests before deployment.
- [ ] verify GitHub Actions logs do not contain production secrets.
- [ ] verify GitHub Actions shows deploy success and VPS deploy service status.
- [ ] push a small safe change to `main` and confirm automatic deploy.

### Task 10: Cutover cleanup and rollback notes

**Files:**

- Modify: `docs/deploy.md`
- Modify if needed: this plan file

- [ ] keep `/opt/my_tg_bot` for at least one successful production deploy and runtime verification window.
- [ ] document rollback option:

```bash
sudo systemctl stop my-tg-bot.service
cd /srv/my_tg_bot/app && COMPOSE_PROJECT_NAME=my_tg_bot docker compose down
cd /opt/my_tg_bot && docker compose up -d --build --remove-orphans
docker ps --format '{{.Names}} {{.Status}}'
```

Before relying on rollback, verify no new `/srv/my_tg_bot/app` container remains active with the production Telegram token.

- [ ] after confidence window, either archive or remove `/opt/my_tg_bot`.
- [ ] remove stale containers/images only after confirming rollback is no longer needed.
- [ ] update `docs/deploy.md` to mark `/opt/my_tg_bot` as legacy/removed when cleanup is complete.
- [ ] update this plan’s checklist with completed items and any deviations.

## Technical Notes

### Docker Compose variable contract

`docker-compose.yml` should support these variables:

```text
COMPOSE_PROJECT_NAME      compose project name, set outside the file
MY_TG_BOT_IMAGE           image tag, default my-tg-bot:latest
MY_TG_BOT_ENV_FILE        env file path passed to the bot container
MY_TG_BOT_DATA_DIR        host directory mounted to /app/data
MY_TG_BOT_UID             numeric runtime UID inside the container
MY_TG_BOT_GID             numeric runtime GID inside the container
```

Production values:

```text
COMPOSE_PROJECT_NAME=my_tg_bot
MY_TG_BOT_IMAGE=my-tg-bot:latest
MY_TG_BOT_ENV_FILE=/etc/my_tg_bot/my_tg_bot.env
MY_TG_BOT_DATA_DIR=/var/lib/my_tg_bot/data
MY_TG_BOT_UID=101
MY_TG_BOT_GID=104
```

Manual replacement deploy values:

```text
COMPOSE_PROJECT_NAME=my_tg_bot
MY_TG_BOT_IMAGE=my-tg-bot:manual
MY_TG_BOT_ENV_FILE=/etc/my_tg_bot/my_tg_bot.env
MY_TG_BOT_DATA_DIR=/var/lib/my_tg_bot/data
MY_TG_BOT_UID=101
MY_TG_BOT_GID=104
```

A manual replacement deploy uses the same Compose project, env file, and data directory as production. It intentionally replaces the running container until the production deploy service resets `/srv/my_tg_bot/app` to `origin/main` and rebuilds `MY_TG_BOT_IMAGE=my-tg-bot:latest`.

### Security boundary

This setup prevents GitHub Actions and `cicd` from directly reading production env files or database files. It does not prevent malicious code merged into `main` from reading secrets at runtime after deployment.

Current policy for this private bot:

- no branch protection is required for now.
- direct push to `main` deploys production.
- that direct-push deployment risk is explicitly accepted.

Future hardening if repository access broadens:

- require pull requests.
- require status checks.
- restrict direct pushes.
- optionally require GitHub Actions environment approval for `production`.

### Git checkout behavior

The deploy script should use deterministic deployment commands:

```bash
git fetch origin main
git reset --hard origin/main
git clean -fdx
```

Before running destructive commands, it must verify it is operating inside `/srv/my_tg_bot/app` and that the remote URL is `git@github.com:mjh-sakh/my_tg_bot.git`.

The deploy script must use strict GitHub host key checking for non-interactive systemd runs, for example:

```bash
GIT_SSH_COMMAND="ssh -i /etc/ssh/deploy-keys/tg-bot_github -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ssh/ssh_known_hosts -o StrictHostKeyChecking=yes"
```

### Production secrets

Production secrets live only on the VPS:

```text
/etc/my_tg_bot/my_tg_bot.env
```

They should be:

```text
owner: root:root
mode: 600
```

GitHub Actions should not receive:

- `TELEGRAM_TOKEN`
- `OPENROUTER_KEY`
- `TOGETHER_API_KEY`
- `ADMIN_ID`

### Service files in repo vs installed service files

The repo contains canonical source versions under `deploy/`. The actual files used by systemd are installed copies:

```text
deploy/systemd/my-tg-bot.service          -> /etc/systemd/system/my-tg-bot.service
deploy/systemd/my-tg-bot-deploy.service   -> /etc/systemd/system/my-tg-bot-deploy.service
deploy/scripts/deploy-my-tg-bot           -> /usr/local/sbin/deploy-my-tg-bot
deploy/sudoers/cicd-my-tg-bot             -> /etc/sudoers.d/cicd-my-tg-bot
```

After editing repo versions, reinstall the copies on the VPS and run:

```bash
sudo systemctl daemon-reload
```

## Plan Review

### Problem / solution fit

- The plan changes production from local rsync to GitHub-triggered, VPS-pulled deployment.
- It preserves the existing Docker Compose runtime and SQLite bind mount model.
- It keeps direct local deploy available as a temporary manual replacement of the active stack.
- It moves env/data/app paths to clearer production locations.

### Scope control

- App features and bot behavior are intentionally out of scope.
- Database schema changes are out of scope.
- Replacing Docker with direct systemd Python execution is out of scope.
- The only Docker/runtime changes are those needed for path configurability and non-root container execution.

### Over-engineering check

- No deployment orchestrator, artifact registry, release manager, or custom daemon is introduced.
- The design uses standard tools already present or already chosen: GitHub Actions, SSH, systemd, Git, Docker Compose.
- The source-controlled deploy assets are plain text files with direct install targets.

### Testing coverage

- Each code-changing task includes validation.
- Production deploy is tested manually before GitHub Actions cutover.
- `cicd` permission boundaries are verified explicitly.
- Runtime Telegram behavior and SQLite persistence are verified after cutover.

### Convention fit

- Plan file is under `docs/plans/` like the existing project plan.
- Deployment docs stay in `docs/deploy.md`.
- Direct helper script remains under `scripts/`.
- New deployment infrastructure lives under a clear top-level `deploy/` directory.

## Post-Completion

- Confirm the GitHub repo deploy key has read-only access only.
- Direct-push deployment risk is accepted for this private bot; revisit branch protection if repo access broadens.
- Confirm GitHub Actions environment approval if manual production approval is desired.
- Keep the local `~/.ssh/tg-bot-deploy.md` operational notes in sync if VPS credentials or paths change.
- After a successful confidence window, remove or archive legacy `/opt/my_tg_bot`.
