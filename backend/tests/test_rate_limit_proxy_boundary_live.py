"""
bd:deps-2026-09 iter2 (CHRIS-16/Q-10) — live-`uvicorn` integration tests
for `api/middleware/rate_limit.py`'s ASGI-server-boundary proxy-header
trust, closing the gap `tests/api/test_rate_limit_middleware.py`'s
`TestClient`-based tests structurally CANNOT see.

Root cause (both Chris's and Quinn's independent live-curl reproductions,
`outputs/deps-2026-09/14-chris-review.md` CHRIS-16 / `15-quinn-review.md`
Q-10): uvicorn/gunicorn's OWN proxy-header trust (default
`forwarded_allow_ips='127.0.0.1'`) rewrites `scope["client"]`/
`request.client.host` from a spoofed `X-Forwarded-For` BEFORE the
application layer (this app's `TRUSTED_PROXIES` allowlist,
`core/config.py` + this middleware's `_is_trusted_proxy()`) ever runs,
whenever the connecting TCP peer happens to be loopback. `TestClient(app)`
calls the ASGI `app` callable in-process and never goes through uvicorn's
real socket-handling code (`ProxyHeadersMiddleware` lives in
`uvicorn/middleware/proxy_headers.py`, outside the `app` object entirely
— confirmed via source inspection) — so no `TestClient`-based test can
ever exercise this bug, which is exactly why it survived iter1's fix pack
undetected by any of its own tests, including the intentionally-adversarial
ones (`test_rate_limit_middleware.py::TestRateLimitKeyingNotSpoofable`).

These tests boot a REAL `uvicorn` subprocess (`python -m uvicorn main:app`,
matching how `docker-compose.dev.yml` and, via `gunicorn`, the prod/ghcr
compose files actually run this app) and hit it over a real loopback
socket with `httpx` — the only way to observe or regression-test this
class of bug at all.

Marked `integration` (deselected by `backend/pytest.ini`'s default
`-m "not integration"`, same convention as `test_user_simulation.py`) —
each test boots a fresh subprocess against the real Postgres/Redis this
sandbox has running, needs a few real seconds, not appropriate for the
default fast unit-test run. Run explicitly:
    pytest backend/tests/test_rate_limit_proxy_boundary_live.py -m integration -v
"""

import os
import socket
import subprocess
import sys
import tempfile
import time

import httpx
import pytest
import redis as redis_sync

pytestmark = pytest.mark.integration

BACKEND_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
LOGIN_PATH = "/api/v1/auth/google"

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://stockviz:stockviz@localhost:5432/stockviz"
)
JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "dev-only-secret-key-0123456789abcdef")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _read_log(logfile) -> str:
    logfile.flush()
    logfile.seek(0)
    return logfile.read().decode(errors="replace")


def _wait_ready(port: int, proc: subprocess.Popen, logfile, timeout: float = 30.0) -> None:
    # bd:deps-2026-09 iter2 own-run: per-attempt timeout=5.0, not the more
    # obvious 1.0 — `/api/health` (system.py) does real synchronous
    # Postgres (`SELECT 1`) + Redis round-trips on EVERY call (no cache),
    # and this app's SQLAlchemy engine runs `echo=True`; against a
    # just-booted app whose asyncpg pool is still cold, single calls
    # measured up to ~2.2s wall time in this sandbox. A too-short
    # per-attempt timeout here doesn't fail cleanly — it makes every
    # readiness probe itself time out forever, masking a healthy server as
    # "never becomes ready" (diagnosed via a standalone repro: identical
    # symptom with stdlib `urllib.request`, ruling out an httpx-specific
    # bug).
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"uvicorn subprocess exited early (rc={proc.returncode}):\n{_read_log(logfile)}"
            )
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=5.0, trust_env=False)
            if r.status_code < 500:
                return
        except Exception as e:  # noqa: BLE001 - readiness poll, retry
            last_err = e
        time.sleep(0.25)
    raise RuntimeError(
        f"uvicorn did not become ready within {timeout}s (last error: {last_err})\n"
        f"{_read_log(logfile)}"
    )


def _launch_uvicorn(
    port: int, forwarded_allow_ips: str, trusted_proxies: str = ""
) -> tuple[subprocess.Popen, "tempfile._TemporaryFileWrapper"]:
    """Launch a real `uvicorn main:app` subprocess.

    `forwarded_allow_ips` is passed via the `$FORWARDED_ALLOW_IPS` env var
    — own-run confirmed (uvicorn 0.52.4 `--help`: "--forwarded-allow-ips
    ... Defaults to the $FORWARDED_ALLOW_IPS environment variable if
    available, or '127.0.0.1'"; verified live in this session with a
    throwaway ASGI app: unset -> spoofed XFF from loopback rewrites
    `scope['client']`; `FORWARDED_ALLOW_IPS=""` -> it does not) — this is
    exactly the mechanism `docs/deploy-gha.md` § Proxy trust documents as
    the (currently unwired, R1) fix for `docker-compose.dev.yml`'s plain
    `uvicorn` command.

    Output goes to a real temp FILE, not `subprocess.PIPE` — own-run
    diagnosed root cause of this test's first-draft hang: this app's
    SQLAlchemy engine runs with `echo=True` (very verbose per-query
    logging), and an unread `PIPE` has a small OS buffer (64KB on Linux);
    once repeated `/api/health` polling generated enough query-log output
    to fill it, the child's `write()` to stdout blocked, stalling its
    entire event loop (including responding to already-accepted TCP
    connections) — looked exactly like a hung/dead server from the test's
    side (`ConnectError` while the listen socket was open in the backlog,
    then permanent `ReadTimeout`, confirmed via a minimal repro with vs.
    without a draining reader). A file has effectively unlimited buffer
    and needs no active reader.
    """
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    env["REDIS_URL"] = REDIS_URL
    env["JWT_SECRET_KEY"] = JWT_SECRET_KEY
    env["FORWARDED_ALLOW_IPS"] = forwarded_allow_ips
    env["TRUSTED_PROXIES"] = trusted_proxies
    logfile = tempfile.TemporaryFile(mode="w+b")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(port)],
        cwd=BACKEND_DIR,
        env=env,
        stdout=logfile,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_ready(port, proc, logfile)
    except Exception:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise
    return proc, logfile


def _stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _hit(port: int, xff: str) -> int:
    # trust_env=False everywhere in this file: this sandbox sets
    # HTTPS_PROXY/NO_PROXY env vars for the agent's own outbound traffic
    # (see repo-external environment docs) — own-run confirmed httpx (but
    # NOT stdlib urllib/curl) picks those up by default even for plain
    # `http://127.0.0.1` loopback targets and then hangs (`ReadTimeout`)
    # rather than routing directly. `trust_env=False` bypasses that;
    # unrelated to the actual proxy-header trust this file is testing
    # (that's `request.client.host`/X-Forwarded-For at the ASGI layer, a
    # completely different "proxy").
    resp = httpx.post(
        f"http://127.0.0.1:{port}{LOGIN_PATH}",
        json={"credential": "not-a-real-token"},
        headers={"X-Forwarded-For": xff},
        timeout=10,
        trust_env=False,
    )
    return resp.status_code


class TestLiveUvicornProxyHeaderBoundary:
    def test_unset_forwarded_allow_ips_reproduces_chris16_q10(self):
        """Negative control: reproduces the ORIGINAL bug exactly as both
        reviewers found it — `FORWARDED_ALLOW_IPS` unset (uvicorn's own
        default `'127.0.0.1'` applies), 6 requests from the real loopback
        peer, 6 DIFFERENT spoofed XFF values -> uvicorn rewrites
        `request.client.host` from each spoofed header BEFORE the app's
        `TRUSTED_PROXIES` allowlist (empty by default) ever runs -> 6
        separate rate-limit buckets, the 6th is NEVER blocked. If this
        assertion ever starts failing (6th becomes 429), it means
        uvicorn's own default behavior changed upstream — not a sign our
        fix regressed (our fix is the OTHER two tests below, which pin
        `FORWARDED_ALLOW_IPS` explicitly)."""
        port = _free_port()
        r = redis_sync.Redis.from_url(REDIS_URL)
        r.delete("rate:login:127.0.0.1")
        for i in range(1, 7):
            r.delete(f"rate:login:10.99.99.{i}")
        env_backup = os.environ.pop("FORWARDED_ALLOW_IPS", None)
        logfile = tempfile.TemporaryFile(mode="w+b")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(port)],
            cwd=BACKEND_DIR,
            env={
                **os.environ,
                "DATABASE_URL": DATABASE_URL,
                "REDIS_URL": REDIS_URL,
                "JWT_SECRET_KEY": JWT_SECRET_KEY,
                "TRUSTED_PROXIES": "",
            },
            stdout=logfile,
            stderr=subprocess.STDOUT,
        )
        try:
            _wait_ready(port, proc, logfile)
            statuses = [_hit(port, f"10.99.99.{i}") for i in range(1, 7)]
        finally:
            _stop(proc)
            logfile.close()
            if env_backup is not None:
                os.environ["FORWARDED_ALLOW_IPS"] = env_backup

        buckets_touched = sum(1 for i in range(1, 7) if r.exists(f"rate:login:10.99.99.{i}"))
        assert 429 not in statuses, (
            f"pre-fix baseline was expected to bypass the limiter entirely "
            f"(never 429) — statuses={statuses}. If uvicorn's upstream "
            f"default changed, update this negative control."
        )
        assert buckets_touched == 6, (
            f"expected all 6 spoofed XFF values to each get their own "
            f"bucket (the bug) — only {buckets_touched}/6 buckets created"
        )
        assert r.exists("rate:login:127.0.0.1") is False or r.get("rate:login:127.0.0.1") in (
            None,
            b"0",
        ), "the real peer's own bucket should be untouched — every request's identity came from XFF, not the peer"

    def test_forwarded_allow_ips_empty_spoofed_xff_collapses_to_one_bucket(self):
        """(a) — the fix. `TRUSTED_PROXIES` unset (default) ->
        `FORWARDED_ALLOW_IPS=""` (the value `gunicorn.conf.py`/docs
        recommend deriving from it). 6 requests from loopback, 6 DIFFERENT
        spoofed XFF values -> uvicorn must NOT rewrite `request.client.host`
        (own-run confirmed `_TrustedHosts("")` trusts nothing, including
        127.0.0.1) -> every request's real identity is the peer,
        127.0.0.1 -> ONE bucket -> 6th request is 429."""
        port = _free_port()
        r = redis_sync.Redis.from_url(REDIS_URL)
        r.delete("rate:login:127.0.0.1")
        for i in range(1, 7):
            r.delete(f"rate:login:10.88.88.{i}")

        proc, logfile = _launch_uvicorn(port, forwarded_allow_ips="", trusted_proxies="")
        try:
            statuses = [_hit(port, f"10.88.88.{i}") for i in range(1, 7)]
        finally:
            _stop(proc)
            logfile.close()

        assert statuses[-1] == 429, (
            f"expected the 6th request to be rate-limited (all 6 spoofed "
            f"XFF values collapse to the real peer 127.0.0.1 when "
            f"FORWARDED_ALLOW_IPS=''), got statuses={statuses} — "
            f"CHRIS-16/Q-10 regression"
        )
        buckets_touched = sum(1 for i in range(1, 7) if r.exists(f"rate:login:10.88.88.{i}"))
        assert buckets_touched == 0, (
            f"expected ZERO per-spoofed-IP buckets (identity must be the "
            f"real peer, not the header) — {buckets_touched}/6 were created"
        )
        assert r.get("rate:login:127.0.0.1") is not None, (
            "expected the shared real-peer bucket to exist and be "
            "incremented 6 times"
        )

    def test_trusted_proxy_configured_rightmost_untrusted_hop(self):
        """(b) — `TRUSTED_PROXIES=127.0.0.1` (simulating the prod/dev
        topology where the ASGI server's real peer IS a legitimate,
        configured reverse proxy) -> `FORWARDED_ALLOW_IPS=127.0.0.1` (same
        value, single source of truth per `gunicorn.conf.py`/docs).

        Part 1 (the prod "inverse case" from the bug report — TRUSTED_
        PROXIES empty + real peer != loopback would make EVERY user share
        Caddy's IP as one bucket): with TRUSTED_PROXIES correctly
        configured, 6 DIFFERENT real users (single-hop XFF each) behind
        the trusted peer must NOT collapse into one bucket — none of the
        first 6 requests should be 429 (each user's own count is only 1).

        Part 2 — rightmost-untrusted-hop parsing (item 2, CHRIS-16/Q-10
        fix): a 2-hop XFF chain `"<attacker>, 127.0.0.1"` (attacker
        appends a spoofed trusted-looking hop after their own IP) must
        resolve to the attacker's IP (the RIGHTMOST entry that is NOT
        itself a trusted proxy), not to 127.0.0.1 and not to the leftmost
        entry blindly."""
        port = _free_port()
        r = redis_sync.Redis.from_url(REDIS_URL)
        for i in range(1, 7):
            r.delete(f"rate:login:192.0.2.{i}")
        r.delete("rate:login:192.0.2.9")
        r.delete("rate:login:127.0.0.1")

        proc, logfile = _launch_uvicorn(port, forwarded_allow_ips="127.0.0.1", trusted_proxies="127.0.0.1")
        try:
            statuses = [_hit(port, f"192.0.2.{i}") for i in range(1, 7)]
            assert 429 not in statuses, (
                f"6 DIFFERENT real users behind a correctly-configured "
                f"trusted proxy must each get their own bucket, not "
                f"collapse into one — statuses={statuses} (this is the "
                f"prod 'inverse case' from the bug report: empty allowlist "
                f"+ non-loopback peer = every user shares Caddy's IP as "
                f"one bucket; TRUSTED_PROXIES=127.0.0.1 here is standing "
                f"in for 'peer is a configured trusted proxy')"
            )
            for i in range(1, 7):
                assert r.get(f"rate:login:192.0.2.{i}") == b"1", (
                    f"rate:login:192.0.2.{i} should be exactly 1 (its own "
                    f"isolated bucket) — got {r.get(f'rate:login:192.0.2.{i}')!r}"
                )

            # Part 2: 2-hop chain, rightmost-untrusted-hop resolution.
            status = _hit(port, "192.0.2.9, 127.0.0.1")
        finally:
            _stop(proc)
            logfile.close()

        assert status != 429, f"single hit, should not be rate-limited yet, got {status}"
        assert r.get("rate:login:192.0.2.9") == b"1", (
            f"2-hop XFF '192.0.2.9, 127.0.0.1' must resolve to the "
            f"RIGHTMOST untrusted hop (192.0.2.9), not the leftmost or the "
            f"trusted proxy entry — got {r.get('rate:login:192.0.2.9')!r}"
        )
        assert r.get("rate:login:127.0.0.1") is None, (
            "the trusted-proxy hop (127.0.0.1) itself must never be used "
            "as a rate-limit identity — it appeared in the XFF chain but "
            "is a configured trusted proxy, not a client"
        )
