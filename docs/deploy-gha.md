# Deploy ShotockViz via GitHub Actions → fresh droplet (188.166.234.146)

> New, **standalone** droplet — separate from the ShoDe Town shared droplet described in
> `docs/deploy.md`. That doc + `scripts/deploy.sh` + `docker-compose.prod.yml` are untouched
> and still apply to the OLD shared droplet. This doc covers the new flow: GitHub Actions
> builds images, pushes to GHCR, then SSHes into the droplet to pull + `up -d`. The server
> itself never runs `docker build`.

## Prerequisites (R0 — do these before the first deploy)

1. **DNS**: an A record for your `DOMAIN` (e.g. `stock.shode.dev`) → `188.166.234.146`.
   Caddy's automatic Let's Encrypt TLS **will fail** if this isn't in place first.
2. **Google OAuth**: add `https://<DOMAIN>` to Google Cloud Console → OAuth 2.0 Client →
   Authorized JavaScript origins.
3. Nothing else is installed on the droplet yet — `scripts/bootstrap-server.sh` does that.

## Order of operations

1. **Bootstrap the server** (once, from your Mac):
   ```bash
   ssh my-do 'bash -s' < scripts/bootstrap-server.sh
   ```
   Installs Docker Engine + compose plugin, opens ufw (22/80/443, OpenSSH allowed first),
   creates `/opt/shotockviz`, and writes a starter `.env` **only if one doesn't already exist**.

2. **Set GitHub secrets/variables** (once, from your Mac — needs `gh` logged in):
   ```bash
   bash scripts/setup-gh-secrets.sh --repo shode666/shotockviz
   ```
   Generates a deploy-only ed25519 keypair, authorizes it on the server, and sets:
   - secrets: `DEPLOY_SSH_KEY`, `VITE_GOOGLE_CLIENT_ID`
   - variables: `DEPLOY_HOST`, `DEPLOY_USER`, `DOMAIN`, `DEPLOY_KNOWN_HOSTS`

3. **Edit `.env` on the server** — `ssh my-do` then edit `/opt/shotockviz/.env`
   (already `chmod 600`, already gitignored, never leaves the server). Keys that MUST change
   from the placeholder (see `.env.example` for the full list):
   - `POSTGRES_PASSWORD`, `DATABASE_URL` (matching password), `JWT_SECRET_KEY`
   - `FINNHUB_API_KEY`, `CORS_ORIGINS` (`https://<DOMAIN>`)
   - `DOMAIN`, `CADDY_EMAIL`, `GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID`
   - `TRUSTED_PROXIES` — see § Proxy trust below; safe to leave empty for the default
     `docker-compose.ghcr.yml` topology (backend not host-port-exposed, only reachable
     from Caddy inside `stockviz-net`).

## Proxy trust (`TRUSTED_PROXIES`)

bd:deps-2026-09 iter2 (CHRIS-16/Q-10). Two independent layers decide whether a request's
`X-Forwarded-For` header is honored for rate-limit client-IP identity, and BOTH must agree
or the weaker one wins:

1. **ASGI server** (uvicorn/gunicorn) — its own `forwarded_allow_ips`, defaults to trusting
   `127.0.0.1` regardless of anything in this app's config. `backend/gunicorn.conf.py` derives
   this from `TRUSTED_PROXIES` and is auto-loaded by `gunicorn` (the command
   `docker-compose.ghcr.yml`/`docker-compose.prod.yml` both run) with **no compose edit
   needed** — own-run confirmed: `gunicorn --help` defaults `-c/--config` to `./gunicorn.conf.py`,
   and the Dockerfile's `WORKDIR /app` (where that file lands) is gunicorn's CWD.
2. **App layer** — `api/middleware/rate_limit.py`'s `TRUSTED_PROXIES` allowlist (this repo's
   `core/config.py` setting), which only ever runs AFTER layer 1 has already decided what
   `request.client.host` is.

Leaving `TRUSTED_PROXIES` empty (default) is safe end-to-end: layer 1 trusts nothing
(`gunicorn.conf.py` sets `forwarded_allow_ips=""`, own-run confirmed this makes uvicorn's
`_TrustedHosts` reject even `127.0.0.1`), layer 2 falls back to the raw socket peer. The
tradeoff (documented, not fixed by this bd): every request that legitimately passes through
Caddy then shares Caddy's own container IP as ONE rate-limit bucket — still correctly
enforced, just coarser per-real-user granularity. To get per-real-user buckets behind Caddy,
set `TRUSTED_PROXIES` to the `stockviz-net` bridge subnet (`docker network inspect
<project>_stockviz-net | grep Subnet`) on the server's `.env` — both layers read the same var.

**Known gap, not closed by this bd (R1 — logged in
`outputs/deps-2026-09/16-dave-iter1-fixes.md` § iter 2):** `docker-compose.dev.yml`'s backend
`command:` runs plain `uvicorn` (not `gunicorn` — `gunicorn.conf.py` does not apply), and
uvicorn's own env-var-driven default (`$FORWARDED_ALLOW_IPS`, own-run confirmed via uvicorn
0.52.4 CLI `--help` + a live test) never reaches the dev container because that variable isn't
in `docker-compose.dev.yml`'s backend `environment:` allowlist. Compose files are read-only on
this branch; the fix is a 1-line addition (`FORWARDED_ALLOW_IPS: ${TRUSTED_PROXIES:-}` next to
the existing `environment:` entries) for whoever picks up that follow-up.

4. **Run the workflow** (manual trigger — `workflow_dispatch` only, matches CI's trigger style
   in `.github/workflows/ci.yml:4`):
   ```bash
   gh workflow run deploy.yml --repo shode666/shotockviz
   # or override the image tag / skip migrations:
   gh workflow run deploy.yml --repo shode666/shotockviz -f run_migrations=false -f image_tag=<sha>
   ```
   This builds+pushes `backend`, `frontend`, `caddy` to
   `ghcr.io/shode666/shotockviz-<service>:<sha>` (+ `:latest`), then SSHes to the droplet,
   pulls, `up -d --remove-orphans`, runs `python scripts/init_db.py` (unless disabled), and
   polls `/api/health` for up to 90s before declaring success.

   > **First deploy on a fresh DB** runs `backend/scripts/init_db.py`, not a bare
   > `alembic upgrade head` — the migration history alone can't create the base schema
   > (see script docstring for root cause), so it auto-detects a fresh DB and bootstraps
   > via `create_all` + `alembic stamp head` before falling back to normal `upgrade head`
   > on every later run.

5. **Verify**:
   ```bash
   curl -sf https://<DOMAIN>/api/health
   ssh my-do 'cd /opt/shotockviz && docker compose -f docker-compose.ghcr.yml ps'
   ```

## Rollback

Re-run the workflow pinned to the previous good sha:
```bash
gh workflow run deploy.yml --repo shode666/shotockviz -f image_tag=<old-sha>
```
The previous image tag is still in GHCR (images aren't deleted on deploy — only
`docker image prune -f` removes untagged/dangling local layers on the server after each run).

## Open questions

- **Ollama**: `PRODUCTION_DEPLOY.md` documents an `ollama` service, but neither
  `docker-compose.prod.yml` nor this new `docker-compose.ghcr.yml` includes one — it does not
  exist in the compose files actually in the repo. Not added here per Oliver's brief; confirm
  with the team whether AI chat needs it on this droplet before relying on `/api/ai/*`.
- **Migration failure mid-deploy**: if `init_db.py` fails after `up -d` already swapped
  containers to the new image, the job fails but containers are left running on the new
  (possibly schema-incompatible) image. No automatic rollback of the compose state is
  implemented — manual `image_tag=<old-sha>` re-run is the recovery path (see Rollback above).
  Resolved by this fix: the *specific* fresh-DB failure seen in live run 33715284627
  (`UndefinedTable: relation "transactions" does not exist"`) — `init_db.py` now detects a
  fresh DB and bootstraps via `create_all` instead of running a bare `alembic upgrade head`
  against an empty schema.
- **`models/note.py` (`StockNote` / `stock_notes` table) is not imported by ANY existing
  bootstrap path** — not `core/database.py:create_tables()` (dev), not
  `db/migrations/env.py` (alembic autogenerate target), and there is no migration that
  creates it either. `init_db.py` now imports it explicitly for the fresh-DB `create_all`
  path (see script comments), but an **existing** pre-`init_db.py` production DB that
  predates this fix would still be missing `stock_notes` and would error on
  `api/routes/notes.py` — pre-existing gap, not introduced by this bd; flagging for the team
  to decide whether a proper migration is needed for already-deployed databases.
