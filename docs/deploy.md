# Deploy to the Netcup VPS

Production deployment is pull-based:

```text
GitHub Actions SSHes as cicd
  -> starts my-tg-bot-deploy.service
  -> VPS pulls origin/main with its read-only deploy key
  -> Docker Compose rebuilds/restarts the bot
```

Direct local deployment is still available as a root/admin operation, but it is an intentional temporary replacement of the active production stack. It does not run a second bot.

## Runtime shape

- one Docker Compose service: `bot`
- one active Compose project for the production token: `my_tg_bot`
- persistent SQLite file in the container: `/app/data/bot.sqlite`
- locker HTTP API in the bot container: `GET /locker/auth`, `POST /locker/logs`
- Docker port publish: host `127.0.0.1:8080` to container `8080`
- production host data directory: `/var/lib/my_tg_bot/data`
- production env file: `/etc/my_tg_bot/my_tg_bot.env`
- production app checkout: `/srv/my_tg_bot/app`

Legacy path `/opt/my_tg_bot` is kept only as a rollback source until migration is fully verified.

## Production paths

```text
/srv/my_tg_bot/app                           git checkout of main
/var/lib/my_tg_bot/data                      persistent SQLite data
/etc/my_tg_bot/my_tg_bot.env                 production secrets/settings
/usr/local/sbin/deploy-my-tg-bot             root-owned deploy script
/etc/systemd/system/my-tg-bot.service        Docker Compose stack unit
/etc/systemd/system/my-tg-bot-deploy.service deploy trigger unit
/etc/sudoers.d/cicd-my-tg-bot                limited cicd sudoers rule
```

## GitHub prerequisites

Repository Actions secrets:

```text
VPS_HOST
VPS_PORT
VPS_USER=cicd
VPS_SSH_KEY
VPS_KNOWN_HOSTS
```

The VPS also needs a read-only GitHub deploy key:

```text
/etc/ssh/deploy-keys/tg-bot_github
```

The public key must be added to the GitHub repository as a read-only deploy key.

Production application secrets are **not** stored in GitHub Actions. They live only on the VPS in:

```text
/etc/my_tg_bot/my_tg_bot.env
```

Required values include at least the variables shown in `.env.example`, such as Telegram/API tokens, admin ID, model settings, and message limits.

The locker HTTP API listens on container port `8080`, and Docker publishes it on host loopback only at `127.0.0.1:8080`. Public access should go through nginx exact-match proxy locations for `/locker/auth` and `/locker/logs`. The API is unauthenticated plain HTTP. Expose it only where that risk is acceptable.

## CI/CD production deployment

Production deploys are triggered by `.github/workflows/deploy.yml` on:

- push to `main`
- manual `workflow_dispatch`

The workflow runs tests, then SSHes as `cicd` and runs only:

```bash
sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service
sudo -n /usr/bin/systemctl show my-tg-bot-deploy.service -p ActiveState -p Result -p ExecMainStatus --no-pager
```

`cicd` should not be able to read production secrets or modify production files directly.

Current branch policy for this private bot:

- no branch protection is required for now
- direct push to `main` deploys production
- this risk is accepted for the private repo

If repository access broadens, add required PRs/status checks before relying on automatic production deploys.

## VPS bootstrap / install

Run as root on the VPS.

Create directories:

```bash
install -d -m 755 -o root -g root /srv/my_tg_bot
install -d -m 755 -o root -g root /srv/my_tg_bot/app
install -d -m 750 -o tg-bot -g tg-bot /var/lib/my_tg_bot/data
install -d -m 700 -o root -g root /etc/my_tg_bot
install -d -m 700 -o root -g root /etc/ssh/deploy-keys
```

Migrate the current env and data from the legacy path:

```bash
install -m 600 -o root -g root /opt/my_tg_bot/.env /etc/my_tg_bot/my_tg_bot.env
rsync -a /opt/my_tg_bot/data/ /var/lib/my_tg_bot/data/
chown -R tg-bot:tg-bot /var/lib/my_tg_bot/data
chmod 750 /var/lib/my_tg_bot/data
chmod 640 /var/lib/my_tg_bot/data/bot.sqlite
```

Install GitHub host keys for non-interactive root/systemd git pulls. Verify fingerprints against GitHub's published SSH key fingerprints before installing:

```bash
ssh-keyscan github.com > /tmp/github_known_hosts
install -m 644 -o root -g root /tmp/github_known_hosts /etc/ssh/ssh_known_hosts
ssh-keygen -F github.com -f /etc/ssh/ssh_known_hosts
rm -f /tmp/github_known_hosts
```

Install repo-owned deployment assets:

```bash
cp deploy/scripts/deploy-my-tg-bot /usr/local/sbin/deploy-my-tg-bot
chown root:root /usr/local/sbin/deploy-my-tg-bot
chmod 755 /usr/local/sbin/deploy-my-tg-bot

cp deploy/systemd/my-tg-bot.service /etc/systemd/system/my-tg-bot.service
cp deploy/systemd/my-tg-bot-deploy.service /etc/systemd/system/my-tg-bot-deploy.service
chown root:root /etc/systemd/system/my-tg-bot.service /etc/systemd/system/my-tg-bot-deploy.service
chmod 644 /etc/systemd/system/my-tg-bot.service /etc/systemd/system/my-tg-bot-deploy.service

cp deploy/sudoers/cicd-my-tg-bot /etc/sudoers.d/cicd-my-tg-bot
chown root:root /etc/sudoers.d/cicd-my-tg-bot
chmod 440 /etc/sudoers.d/cicd-my-tg-bot
visudo -cf /etc/sudoers.d/cicd-my-tg-bot

systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/my-tg-bot.service
systemd-analyze verify /etc/systemd/system/my-tg-bot-deploy.service
```

## First production deploy

Validate GitHub access from the VPS:

```bash
GIT_SSH_COMMAND='ssh -i /etc/ssh/deploy-keys/tg-bot_github -o IdentitiesOnly=yes -o UserKnownHostsFile=/etc/ssh/ssh_known_hosts -o StrictHostKeyChecking=yes' \
  git ls-remote git@github.com:mjh-sakh/my_tg_bot.git refs/heads/main
```

Stop the legacy stack when ready for cutover:

```bash
cd /opt/my_tg_bot && docker compose down
```

Start the deploy service:

```bash
sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service
sudo -n /usr/bin/systemctl show my-tg-bot-deploy.service -p ActiveState -p Result -p ExecMainStatus --no-pager
```

A successful one-shot deploy unit returns to `inactive (dead)`, so `systemctl status` may return exit code `3` even when deployment succeeded. Use `systemctl show` for non-failing status output in CI; the `start` command is the command that should fail the deployment if the service fails.

## Direct manual replacement deployment

Use this from the local repo when you want to temporarily run local code on the VPS. This uses the existing root/admin SSH config (`netcup`), not the restricted `cicd` user.

```bash
./scripts/deploy.sh
```

Defaults:

```text
REMOTE_HOST=netcup
REMOTE_DIR=/srv/my_tg_bot/app
REMOTE_DATA_DIR=/var/lib/my_tg_bot/data
REMOTE_ENV_FILE=/etc/my_tg_bot/my_tg_bot.env
COMPOSE_PROJECT_NAME=my_tg_bot
MY_TG_BOT_IMAGE=my-tg-bot:manual
MY_TG_BOT_UID=101
MY_TG_BOT_GID=104
```

The script preserves `.git/` in `/srv/my_tg_bot/app`, uses the server env file, and recreates the same Compose project. To restore `main` afterward:

```bash
ssh netcup 'sudo -n /usr/bin/systemctl start my-tg-bot-deploy.service'
```

## Status and logs

Production services:

```bash
sudo systemctl status --no-pager my-tg-bot.service
sudo systemctl status --no-pager my-tg-bot-deploy.service
sudo journalctl -u my-tg-bot.service -n 100 --no-pager
sudo journalctl -u my-tg-bot-deploy.service -n 100 --no-pager
```

Compose status:

```bash
cd /srv/my_tg_bot/app
COMPOSE_PROJECT_NAME=my_tg_bot docker compose ps
COMPOSE_PROJECT_NAME=my_tg_bot docker compose logs --tail=100 bot
docker ps --filter 'name=my_tg_bot' --format '{{.Names}} {{.Status}}'
```

Only one bot container should be active for the production Telegram token.

## Validation

After deployment:

```bash
cd /srv/my_tg_bot/app
git branch --show-current
git status --short
git rev-parse HEAD

COMPOSE_PROJECT_NAME=my_tg_bot \
MY_TG_BOT_IMAGE=my-tg-bot:latest \
MY_TG_BOT_ENV_FILE=/etc/my_tg_bot/my_tg_bot.env \
MY_TG_BOT_DATA_DIR=/var/lib/my_tg_bot/data \
MY_TG_BOT_UID=101 \
MY_TG_BOT_GID=104 \
docker compose config

docker compose exec bot id
ls -lah /var/lib/my_tg_bot/data
```

Expected container identity:

```text
uid=101(tg-bot) gid=104(tg-bot)
```

Manual bot checks:

- `/start`
- `/whoami`
- `/locker`, `/locker on`, `/locker off`
- one `/chat` request if credentials are ready
- one voice message if credentials are ready
- restart/recreate the container and confirm `/var/lib/my_tg_bot/data/bot.sqlite` remains present

Locker HTTP checks:

```bash
curl -i http://127.0.0.1:8080/locker/auth
curl -i -X POST --data-binary $'{"event":"test"}\n' http://127.0.0.1:8080/locker/logs
curl -i http://<host>/locker/auth
curl -i -X POST --data-binary $'{"event":"test"}\n' http://<host>/locker/logs
```

Use these Windows build URLs:

```text
AuthURL=http://<host>/locker/auth
LogURL=http://<host>/locker/logs
```

## Rollback to legacy deployment

Before rollback, stop the new stack so two long-polling containers do not use the same Telegram token:

```bash
sudo systemctl stop my-tg-bot.service
cd /srv/my_tg_bot/app && COMPOSE_PROJECT_NAME=my_tg_bot docker compose down
cd /opt/my_tg_bot && docker compose up -d --build --remove-orphans
docker ps --format '{{.Names}} {{.Status}}'
```

Keep `/opt/my_tg_bot` until the new deployment has been verified and rollback is no longer needed.
