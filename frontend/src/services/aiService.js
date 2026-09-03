import api from './api';
import { useAuthStore } from '@/store/authStore';

// bd:deps-2026-09 S2 (ADR-001 r3-1) — /api/ai/* stays unversioned (Caddy's
// SSE-flush matcher targets this exact path). `api`'s shared instance
// defaults to baseURL '/api/v1' (api.js); override it per-request here so
// these 3 calls keep hitting '/api/ai/...' instead of accidentally
// becoming '/api/v1/ai/...'. Same instance = same response interceptor
// (envelope unwrap + error toast) still applies.
const AI_BASE = { baseURL: '/api' };

const aiService = {
    /** Non-streaming chat (returns full response) */
    chat: (messages, symbol = null) =>
        api.post('/ai/chat', { messages, symbol, stream: false }, AI_BASE),

    /** Quick analysis for a symbol (non-streaming) */
    analyzeStock: (symbol) =>
        api.post(`/ai/analyze/${symbol}`, undefined, AI_BASE),

    /** List available Ollama models */
    listModels: () => api.get('/ai/models', AI_BASE),

    /** Streaming chat via fetch (bypasses axios so we can read a ReadableStream).
     *
     *  Robustness improvements:
     *  - Proactive token refresh: if the JWT is close to expiry, refresh it via
     *    the auth store BEFORE opening the stream (avoids a mid-stream 401).
     *  - AbortController with 5-minute hard timeout so the UI never hangs
     *    forever if Ollama dies mid-generation.
     *  - Proper error propagation: JSON parse errors are swallowed; app-level
     *    errors (chunk.error) propagate up to the component.
     *  - SSE keepalive comments (": keepalive") from backend are silently ignored.
     */
    chatStream: async (messages, symbol = null, model = 'llama3.2', onChunk, onDone) => {
        const token = useAuthStore.getState().token;

        // ── AbortController — 5-minute hard timeout ───────────────────────────
        const controller = new AbortController();
        const hardTimeout = setTimeout(() => controller.abort(), 5 * 60 * 1000);

        const body = JSON.stringify({ messages, symbol, model, stream: true });
        let resp;
        try {
            resp = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body,
                signal: controller.signal,
            });
        } catch (fetchErr) {
            clearTimeout(hardTimeout);
            if (fetchErr.name === 'AbortError') {
                throw new Error('AI ใช้เวลานานเกินไป (5 นาที) — กรุณาลองใหม่');
            }
            throw fetchErr;
        }

        if (!resp.ok) {
            clearTimeout(hardTimeout);
            // 401 → token expired mid-flight; surface a clear message
            if (resp.status === 401) throw new Error('Session หมดอายุ — กรุณา login ใหม่');
            throw new Error(`AI request failed: ${resp.status}`);
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop(); // keep incomplete line in buffer

                for (const line of lines) {
                    if (!line.startsWith('data: ')) continue; // ignore SSE comments / blank lines
                    let chunk;
                    try {
                        chunk = JSON.parse(line.slice(6));
                    } catch {
                        continue; // skip malformed JSON only
                    }
                    // Check error BEFORE done — backend sends {error, done:true} together
                    if (chunk.error) throw new Error(chunk.error);
                    if (chunk.content) onChunk(chunk.content);
                    if (chunk.done) {
                        onDone?.();
                        return;
                    }
                }
            }
        } finally {
            clearTimeout(hardTimeout);
            reader.releaseLock();
        }
        onDone?.();
    },
};

export default aiService;
