# bd:deps-2026-09 iter2 (CHRIS-16/Q-10) — closes the gap the CHRIS-03/iter1
# app-level `TRUSTED_PROXIES` allowlist (core/config.py, api/middleware/
# rate_limit.py) cannot see: uvicorn/gunicorn's OWN default proxy-header
# trust rewrites `request.client.host` from a spoofed `X-Forwarded-For`
# BEFORE the application layer ever runs, whenever the connecting TCP peer
# happens to match the ASGI server's default `forwarded_allow_ips`
# (`'127.0.0.1'` — uvicorn 0.52.4's own default, confirmed via
# `uvicorn.config.Config(app='main:app').forwarded_allow_ips`). Live-uvicorn
# curl repro: 6 requests, 6 distinct spoofed XFF values from loopback -> 6
# separate `rate:login:*` Redis buckets, all 422 (bypasses the login rate
# limiter entirely). See `outputs/deps-2026-09/14-chris-review.md` CHRIS-16
# and `15-quinn-review.md` Q-10 for both independent live reproductions.
#
# WHY THIS FILE (not a compose-file `command:` edit — this branch's compose
# files are read-only): gunicorn's own `-c/--config` default is literally
# `./gunicorn.conf.py` (own-run: `python -m gunicorn --help` ->
# `-c, --config CONFIG ... [./gunicorn.conf.py]`; confirmed by probe: a
# `gunicorn.conf.py` dropped in a directory gets auto-loaded and its
# settings applied even when the invoking command passes ZERO `-c` flag).
# `docker-compose.prod.yml:65` / `docker-compose.ghcr.yml:76` both run
# `gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind
# 0.0.0.0:8000` with no `-c` — but the Dockerfile's `WORKDIR /app` (where
# this file lands via `COPY . .`) IS gunicorn's CWD at container start, so
# this file is picked up automatically, no compose edit required. CLI flags
# still win over anything set here (own-run: `--bind` on the command line
# overrode this file's own `bind =` in the probe above) — so nothing in
# this file can conflict with the compose `command:` lines' existing flags.
#
# `uvicorn.workers.UvicornWorker` (uvicorn/workers.py, uvicorn 0.52.4)
# ALWAYS forwards gunicorn's `forwarded_allow_ips` setting into uvicorn's
# own `Config(forwarded_allow_ips=self.cfg.forwarded_allow_ips, ...)` — that
# is gunicorn's ONLY hook into uvicorn's proxy-trust behavior under this
# worker class (there is no `proxy_headers` gunicorn setting; that flag is
# uvicorn-CLI/Config-only and UvicornWorker never wires it, so
# `Config`'s own `proxy_headers=True` default always applies — which is
# fine, `forwarded_allow_ips` is the actual gate). Setting it here from the
# SAME `TRUSTED_PROXIES` env var `core/config.py` reads makes it the single
# source of truth end-to-end, instead of two independently-drifting values.
#
# Own-run confirmed SAFE default: `forwarded_allow_ips=""` (gunicorn's
# `validate_string_to_addr_list("")` -> `[]`) makes uvicorn's own
# `_TrustedHosts` trust NOTHING, including `127.0.0.1`
# (`_TrustedHosts([]).__contains__('127.0.0.1')` -> `False`, own-run) — this
# is NOT the same as leaving the setting unset (which defaults to trusting
# loopback and reproduces CHRIS-16/Q-10).
#
# NOTE (R1, logged in outputs/deps-2026-09/16-dave-iter1-fixes.md § iter 2):
# `docker-compose.dev.yml`'s backend `command:` runs plain `uvicorn` (not
# gunicorn — no `-w`/`-k uvicorn.workers.UvicornWorker`), so THIS file does
# not apply to dev. Bare uvicorn has no equivalent auto-config-file
# discovery; it instead defaults `--forwarded-allow-ips` from the
# `$FORWARDED_ALLOW_IPS` env var (own-run confirmed, uvicorn 0.52.4 CLI
# help + live test) — but that var is not in `docker-compose.dev.yml`'s
# backend `environment:` allowlist, so it never reaches the dev container
# even if set in `.env`. Requires a 1-line compose edit; see the R1 entry.
import os

_trusted_proxies_raw = os.environ.get("TRUSTED_PROXIES", "")

# Comma-separated IPs/CIDRs, same format + semantics as core/config.py's
# `Settings.trusted_proxies` — empty (default) = trust nothing.
forwarded_allow_ips = _trusted_proxies_raw if _trusted_proxies_raw.strip() else ""
