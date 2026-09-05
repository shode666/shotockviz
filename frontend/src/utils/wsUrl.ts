/**
 * bd:shotockviz-pls — build the /api/ws/prices URL for an authenticated
 * WebSocket handshake.
 *
 * The backend (`main.py websocket_prices`) rejects the handshake (HTTP 403 /
 * close 1008) unless a valid access JWT is presented as the `token` query
 * parameter. useWebSocket only connects when logged in, so a token is always
 * available; it is the same token api.js already sends as a Bearer header on
 * every REST call — no new token management, just transport.
 *
 * Pure function so `node --test` can cover it (no window/WebSocket needed).
 */
export function buildWsUrl(pageProtocol: string, host: string, token: string): string {
    const wsProtocol = pageProtocol === 'https:' ? 'wss:' : 'ws:';
    return `${wsProtocol}//${host}/api/ws/prices?token=${encodeURIComponent(token)}`;
}
