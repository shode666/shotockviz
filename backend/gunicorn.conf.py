# bd:deps-2026-09 iter2 (CHRIS-16/Q-10) — closes a gap the app-level
# `TRUSTED_PROXIES` allowlist (core/config.py, rate_limit.py) can't see:
# uvicorn/gunicorn's OWN proxy-header trust rewrites `request.client.host`
# from a spoofed X-Forwarded-For BEFORE the app layer ever runs, whenever
# the peer matches its default `forwarded_allow_ips` ('127.0.0.1'). Live
# repro: 6 spoofed XFF values from loopback -> 6 separate rate-limit
# buckets, bypassing the login limiter entirely (14-chris-review.md
# CHRIS-16 / 15-quinn-review.md Q-10).
#
# Auto-loaded: gunicorn's `-c/--config` default IS `./gunicorn.conf.py`,
# and the Dockerfile's `WORKDIR /app` (where this lands via `COPY . .`) is
# gunicorn's CWD at container start — no compose edit needed.
# `uvicorn.workers.UvicornWorker` always forwards gunicorn's
# `forwarded_allow_ips` into uvicorn's own `Config`, so deriving it here
# from the SAME `TRUSTED_PROXIES` var core/config.py reads keeps one
# source of truth end-to-end. `forwarded_allow_ips=""` (empty, not unset)
# makes uvicorn's `_TrustedHosts` trust nothing, including 127.0.0.1.
#
# NOTE (R1, outputs/deps-2026-09/16-dave-iter1-fixes.md § iter 2):
# `docker-compose.dev.yml` runs plain `uvicorn` (no gunicorn), so this
# file doesn't apply to dev — it needs `$FORWARDED_ALLOW_IPS` wired into
# that compose file's `environment:` separately.
import os

_trusted_proxies_raw = os.environ.get("TRUSTED_PROXIES", "")

# Comma-separated IPs/CIDRs, same format + semantics as core/config.py's
# `Settings.trusted_proxies` — empty (default) = trust nothing.
forwarded_allow_ips = _trusted_proxies_raw if _trusted_proxies_raw.strip() else ""
