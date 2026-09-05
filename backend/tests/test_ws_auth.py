"""bd:shotockviz-pls — WebSocket handshake auth + per-user alert routing.

Covers:
1. /api/ws/prices rejects a handshake with no/invalid/expired token.
2. A valid access JWT connects, and subscribe/unsubscribe/ping still work
   (frontend useWebSocket.ts sends {"action":"subscribe"} on connect —
   commit 0b7e47b must not break).
3. ConnectionManager.send_to_user hits only the owning user's sockets.
4. _dispatch_ws_message routes alert_triggered per-user (user_id stripped
   from the delivered payload), drops payloads without user_id (fail
   closed), broadcasts data_ready to all, and routes price_update to
   symbol subscribers only.
"""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from core.security import create_access_token
from main import ConnectionManager, _dispatch_ws_message, app, manager

WS_PATH = "/api/ws/prices"


def _connect_should_fail(client: TestClient, url: str) -> None:
    """The server closes with 1008 before accept → Starlette's TestClient
    surfaces the refused handshake as an exception (denial response /
    disconnect, exact type varies by starlette version)."""
    with pytest.raises(Exception):
        with client.websocket_connect(url):
            pass


class TestWebSocketHandshakeAuth:
    def test_no_token_rejected(self):
        client = TestClient(app)
        _connect_should_fail(client, WS_PATH)

    def test_garbage_token_rejected(self):
        client = TestClient(app)
        _connect_should_fail(client, f"{WS_PATH}?token=not-a-jwt")

    def test_expired_token_rejected(self):
        token = create_access_token(
            {"sub": "1", "role": "user"}, expires_delta=timedelta(minutes=-5)
        )
        client = TestClient(app)
        _connect_should_fail(client, f"{WS_PATH}?token={token}")

    def test_token_without_sub_rejected(self):
        token = create_access_token({"role": "user"})
        client = TestClient(app)
        _connect_should_fail(client, f"{WS_PATH}?token={token}")

    def test_valid_token_connects_and_subscribe_flow_works(self):
        token = create_access_token({"sub": "1", "role": "user"})
        client = TestClient(app)
        with client.websocket_connect(f"{WS_PATH}?token={token}") as ws:
            ws.send_json({"action": "subscribe", "symbol": "nvda"})
            assert ws.receive_json() == {"type": "subscribed", "symbol": "NVDA"}
            ws.send_json({"action": "ping"})
            assert ws.receive_json() == {"type": "pong"}
            ws.send_json({"action": "unsubscribe", "symbol": "NVDA"})
            assert ws.receive_json() == {"type": "unsubscribed", "symbol": "NVDA"}
        # disconnect cleans up manager state
        assert len(manager.active) == 0
        assert len(manager.user_ids) == 0


def _fake_ws():
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class TestConnectionManagerUserRouting:
    @pytest.mark.asyncio
    async def test_send_to_user_only_hits_owner_sockets(self):
        m = ConnectionManager()
        ws_owner_a, ws_owner_b, ws_other = _fake_ws(), _fake_ws(), _fake_ws()
        for ws, uid in ((ws_owner_a, 1), (ws_owner_b, 1), (ws_other, 2)):
            m.active.add(ws)
            m.subscriptions[ws] = set()
            m.user_ids[ws] = uid

        await m.send_to_user(1, {"type": "alert_triggered"})

        ws_owner_a.send_json.assert_awaited_once()
        ws_owner_b.send_json.assert_awaited_once()
        ws_other.send_json.assert_not_awaited()


class TestDispatchWsMessage:
    @pytest.fixture(autouse=True)
    def _two_users_connected(self):
        """Register two fake sockets (user 1 and user 2) on the real
        module-level manager, restore after."""
        self.ws_u1, self.ws_u2 = _fake_ws(), _fake_ws()
        for ws, uid in ((self.ws_u1, 1), (self.ws_u2, 2)):
            manager.active.add(ws)
            manager.subscriptions[ws] = set()
            manager.user_ids[ws] = uid
        yield
        for ws in (self.ws_u1, self.ws_u2):
            manager.disconnect(ws)

    @pytest.mark.asyncio
    async def test_alert_triggered_goes_only_to_owner_and_strips_user_id(self):
        await _dispatch_ws_message({
            "type": "alert_triggered",
            "symbol": "NVDA",
            "user_id": 1,
            "data": {"symbol": "NVDA", "condition": "above 100", "price": 101.0, "alert_id": 7},
        })
        self.ws_u1.send_json.assert_awaited_once()
        delivered = self.ws_u1.send_json.await_args.args[0]
        assert "user_id" not in delivered
        assert delivered["data"]["alert_id"] == 7
        self.ws_u2.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_alert_triggered_without_user_id_is_dropped(self):
        """Fail closed — a payload without a routing key must NOT be
        broadcast (that is the leak this bd removes)."""
        await _dispatch_ws_message({
            "type": "alert_triggered",
            "symbol": "NVDA",
            "data": {"alert_id": 7},
        })
        self.ws_u1.send_json.assert_not_awaited()
        self.ws_u2.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_data_ready_still_broadcasts_to_all(self):
        await _dispatch_ws_message({"type": "data_ready", "data_type": "quote", "symbol": "NVDA"})
        self.ws_u1.send_json.assert_awaited_once()
        self.ws_u2.send_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_price_update_goes_to_symbol_subscribers_only(self):
        manager.subscribe(self.ws_u1, "NVDA")
        await _dispatch_ws_message({"type": "price_update", "symbol": "NVDA", "price": 1.0})
        self.ws_u1.send_json.assert_awaited_once()
        self.ws_u2.send_json.assert_not_awaited()
