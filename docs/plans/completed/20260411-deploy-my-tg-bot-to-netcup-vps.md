# Deploy my_tg_bot to the Netcup VPS

Status: Completed on 2026-04-11.

## Overview
- Deploy the current Telegram bot to the existing VPS in a way that is reliable, repeatable, and quick to operate.
- Use the VPS as the runtime for both the bot and its required MongoDB dependency.
- Keep the initial deployment scope focused on getting the bot running in production with persistence and basic restart behavior.
- Expected result:
  - the VPS has the required runtime installed
  - the project can be uploaded over SSH and started without manual one-off steps
  - MongoDB data persists across restarts
  - the bot runs via Telegram polling and can answer `/start`, `/whoami`, `/chat`, and voice messages

## Context
- Local project:
  - Entrypoint: `bot/main.py`
  - The bot uses Telegram polling, not webhooks, so no inbound HTTP port is required for the app itself.
  - The app depends on MongoDB for authorization/history via `bot/clients/mongo_client.py` and `bot/handlers/security.py`.
  - `redis` is declared and a client exists, but it does not appear to be used by the runtime code path.
  - Existing container artifacts already exist: `Dockerfile`, `docker-compose.yml`, `.dockerignore`.
- Current deployment-related gaps in the repo:
  - `docker-compose.yml` assumes external Mongo volumes already exist, which is not true on a clean VPS.
  - There is no deployment doc for this project.
  - `.env.example` does not document every variable relevant to deployment, especially the Mongo connection assumption.
- VPS readiness findings from `ssh-mcp`:
  - Host: Debian 13 on Netcup KVM
  - Resources: ~3.8 GiB RAM, ~113 GiB free disk on `/`, 5 GiB swap
  - Network: outbound DNS resolution for Telegram, Together, and OpenRouter works
  - Installed services already using the host: `nginx` on 80, `xray` on 443, `syncthing`
  - Not currently installed: Docker, Docker Compose, MongoDB, Redis, Git, `uv`, `mise`
  - Python 3.13.5 is present, which is in the project’s supported range, but the project already has a Docker-based path and Mongo is not available as a simple Debian package here
- Existing patterns to follow:
  - Prefer the repo’s existing Dockerfile/compose path rather than inventing a separate runtime model for the first deploy
  - Use `rsync` over SSH from the current dev machine to the VPS for this deployment
  - Use the current local `.env` as the starting production config, then make only the server-specific adjustments required for the containerized Mongo connection

## Chosen Approach
- Recommended approach: install Docker on the VPS and run the bot plus MongoDB as a small Docker Compose stack.
- Upload the repo over SSH (`scp`/`rsync`) to a dedicated app directory on the server for the first deployment.
- Keep the bot on polling; do not involve Nginx or webhook setup.
- Adjust the compose setup so it is self-contained on a fresh host, with named volumes managed by Docker instead of pre-created external volumes.

### Rejected alternatives
- **Run the bot directly with systemd + Python on the host, and install MongoDB natively**
  - Rejected because MongoDB is not available as a simple candidate package on this Debian host, so this becomes more work than the existing container path.
- **Run the bot directly with systemd + Python, but containerize only MongoDB**
  - Rejected for the first deploy because it creates a mixed operating model with more moving parts and less reproducibility.
- **Introduce webhooks behind Nginx**
  - Rejected because the bot already uses polling and does not need inbound app ports to become operational.

## Development Approach
- testing approach: implementation-first, with local validation before touching the server
- keep changes small and focused
- prefer the existing Dockerfile/compose path over a custom deployment framework
- use SSH file transfer for the first deploy unless Git is intentionally installed on the VPS
- document the exact production runbook so future redeploys are repeatable

## Testing Strategy
- Local validation:
  - run `mise exec -- direnv exec . uv run pytest`
  - run a local image build from `Dockerfile`
  - run `docker compose config` after updating `docker-compose.yml`
- Remote validation:
  - verify Docker engine starts on boot
  - run `docker compose up -d --build`
  - inspect `docker compose ps` and bot logs
  - verify MongoDB volume persistence
  - smoke-test the bot from Telegram with `/start` and `/whoami`
  - if credentials are available, test one `/chat` request and one voice transcription flow

## Progress Tracking
- mark completed work with `[x]`
- use `[ ]` for pending work
- add `➕` for newly discovered work
- add `⚠️` for blockers, risks, or open decisions

## Implementation Steps

### Task 1: Make the repository deployment-ready for a clean VPS

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `README.md`
- Create: `docs/deploy.md`

- [x] change Compose-managed Mongo storage from pre-existing external volumes to self-contained named volumes
- [x] add sensible restart behavior for the bot and MongoDB services
- [x] confirm the bot container receives the runtime env vars it needs, including the Mongo URI for the internal Docker network
- [x] document the minimum production secrets and optional variables in `.env.example`
- [x] write a short deployment runbook with upload, start, logs, restart, and update commands
- [x] validate the updated compose configuration locally before moving on

### Task 2: Prepare the VPS runtime and app directory

**Files:**
- Create: `/opt/my_tg_bot/`
- Create: `/opt/my_tg_bot/.env`
- Modify: remote Docker/service state on the VPS

- [x] install Docker and Docker Compose on the VPS
- [x] enable/start the Docker service so containers survive reboot through Docker restart policies
- [x] create a dedicated app directory: `/opt/my_tg_bot`
- [x] confirm no host port mappings are required for the bot stack
- [x] confirm sufficient disk/memory remain after installation

### Task 3: Upload the application and production configuration

**Files:**
- Create: `/opt/my_tg_bot/docker-compose.yml`
- Create: `/opt/my_tg_bot/Dockerfile`
- Create: `/opt/my_tg_bot/bot/...`
- Create: `/opt/my_tg_bot/pyproject.toml`
- Create: `/opt/my_tg_bot/uv.lock`
- Create: `/opt/my_tg_bot/.env`

- [x] use `rsync` from the current dev machine as the deployment transfer method
- [x] upload the repository contents needed for the build while excluding local-only artifacts that should not be deployed
- [x] copy the current local `.env` to `/opt/my_tg_bot/.env` as the starting production config
- [x] update the production `.env` with the server-specific settings required for the containerized deployment, especially the container-network Mongo URI instead of localhost
- [x] keep secrets in the server-side `.env` and out of Git history

### Task 4: Start the stack and verify bot behavior

**Files:**
- Modify: `/opt/my_tg_bot/.env` if runtime corrections are needed
- Modify: `/opt/my_tg_bot/docker-compose.yml` only if deployment-time fixes are required

- [x] build and start the stack on the VPS with Docker Compose
- [x] verify both bot and MongoDB containers are healthy enough to stay running
- [x] inspect bot logs for startup errors, missing env vars, or import/runtime failures
- [x] confirm MongoDB data volumes were created and attached correctly
- [x] smoke-test Telegram commands from a real chat
- [x] test one LLM response path and one transcription path if credentials are ready

### Task 5: Verify acceptance criteria
- [x] verify the stack survives container restarts and a host reboot expectation via Docker restart policy
- [x] verify MongoDB data persists across container recreation
- [x] verify the bot does not require Nginx or any new public port exposure
- [x] verify deployment and rollback/update steps are documented clearly enough to repeat

### Task 6: Final documentation and cleanup
- [x] update `README.md` with a pointer to deployment documentation if needed
- [x] ensure `docs/deploy.md` matches the final commands actually used
- [x] capture any VPS-specific quirks discovered during deployment
- [x] add a simple deploy helper for this specific dev-machine-to-VPS path (`scripts/deploy.sh`)

## Technical Notes
- The bot’s current auth model means `ADMIN_ID` is enough for the admin to access the bot immediately even if the Mongo `users` collection starts empty.
- Because the bot uses polling, `nginx` and existing ports 80/443 do not need to be modified for the initial deployment.
- `redis` appears unused in the current runtime and is out of scope for this deployment.
- The server already has Python 3.13.5, but using Docker keeps the runtime closer to the repo’s existing deployment artifacts and avoids host-level dependency drift.

## Post-Completion
- [x] manually confirm the production secrets are stored securely on the VPS
- [x] once the manual flow is proven, add a small machine-specific deploy helper for this repo/VPS pair so future deploys are one command instead of a repeated checklist
