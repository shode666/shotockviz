"""bd:deps-2026-09 iter2 re-verify (CHRIS-16/Q-10 follow-up).

Chris's iter2 re-verify found that Dave's own regression test for the
rightmost-untrusted-hop parsing fix
(`test_rate_limit_proxy_boundary_live.py::
TestLiveUvicornProxyHeaderBoundary::
test_trusted_proxy_configured_rightmost_untrusted_hop`, part 2) uses a
2-hop XFF fixture (`"192.0.2.9, 127.0.0.1"`) where the trusted hop is
already rightmost - so the correct "rightmost untrusted hop" algorithm
and the OLD, buggy "always leftmost" algorithm coincidentally produce
the SAME answer (`192.0.2.9`) for that specific input. Hand-mutating
`_rightmost_untrusted_ip` back to `hops[0]` (leftmost) still passes
that test unchanged - own-run confirmed, see 14-chris-review.md
§ iter 2 re-verify.

This is a pure-function, fast unit test (no subprocess boot needed) -
it discriminates the two algorithms with a 3-hop fixture where an
attacker-injected decoy sits leftmost and the real (trusted-proxy-
observed) client IP sits in the middle, ahead of the trusted hop.
"""
from api.middleware.rate_limit import RateLimitMiddleware


class TestRightmostUntrustedHopDiscriminates:
    """Given TRUSTED_PROXIES=127.0.0.1, a 3-hop X-Forwarded-For chain
    where an attacker-injected decoy IP sits leftmost and the real
    client IP (as observed by the actual trusted proxy) sits just
    before the trusted hop, the middleware should resolve to the real
    client IP - not the attacker's leftmost decoy."""

    def test_decoy_leftmost_does_not_win_over_real_rightmost_untrusted_hop(self, monkeypatch):
        # Given a 3-hop chain: decoy (attacker-injected), real client,
        # trusted proxy
        monkeypatch.setattr(
            "api.middleware.rate_limit.settings.trusted_proxies",
            "127.0.0.1",
        )
        xff = "203.0.113.5, 192.0.2.9, 127.0.0.1"

        # When resolving the rightmost untrusted hop
        result = RateLimitMiddleware._rightmost_untrusted_ip(xff)

        # Then it's the real client IP the trusted proxy actually saw,
        # not the attacker's leftmost decoy
        assert result == "192.0.2.9"
        assert result != xff.split(",")[0].strip(), (
            "this fixture must discriminate leftmost vs rightmost-untrusted "
            "- if it doesn't, the test proves nothing about which algorithm "
            "is actually running"
        )

    def test_single_hop_from_trusted_peer_resolves_to_itself(self, monkeypatch):
        # Given TRUSTED_PROXIES=127.0.0.1 and a single-hop XFF
        monkeypatch.setattr(
            "api.middleware.rate_limit.settings.trusted_proxies",
            "127.0.0.1",
        )

        # When resolving
        result = RateLimitMiddleware._rightmost_untrusted_ip("198.51.100.4")

        # Then the single hop is returned as-is
        assert result == "198.51.100.4"

    def test_all_hops_trusted_falls_back_to_leftmost_per_docstring(self, monkeypatch):
        # Given every hop in the chain is itself a trusted proxy (a
        # malformed/attacker chain with no real client segment left)
        monkeypatch.setattr(
            "api.middleware.rate_limit.settings.trusted_proxies",
            "127.0.0.1,10.0.0.5",
        )

        # When resolving
        result = RateLimitMiddleware._rightmost_untrusted_ip("10.0.0.5, 127.0.0.1")

        # Then it falls back to the leftmost entry (documented edge case)
        assert result == "10.0.0.5"
