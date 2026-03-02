/**
 * AI Chat Panel — floating personal investment assistant
 * Powered by Ollama (local LLM) with portfolio + chart context.
 *
 * Position: bottom-right, above StatusBar (~40px), clear of right Stats panel.
 * SSE streaming works only when Caddy has flush_interval -1 on /api/ai/*.
 */
import { useState, useRef, useEffect, useCallback } from 'react';
import { X, Send, Sparkles, RefreshCw, Bot, ChevronDown } from 'lucide-react';
import aiService from '@/services/aiService';
import useAppStore from '@/store/appStore';

interface Message {
    role: 'user' | 'assistant';
    content: string;
    error?: boolean;
}

const SUGGESTED_PROMPTS = [
    'วิเคราะห์หุ้นตัวนี้ให้หน่อย',
    'ดู RSI แล้วแนวโน้มเป็นอย่างไร?',
    'พอร์ตตอนนี้เป็นยังไงบ้าง?',
    'อธิบาย Bollinger Bands ให้หน่อย',
];

export default function AIChatPanel() {
    const { selectedStock } = useAppStore();
    const [open, setOpen] = useState(false);
    const [messages, setMessages] = useState<Message[]>([]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const [waitingForFirstToken, setWaitingForFirstToken] = useState(false);
    const [available, setAvailable] = useState<boolean | null>(null);
    const [modelName, setModelName] = useState<string>('llama3.2');
    const bottomRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    // Check Ollama availability + grab actual model name
    useEffect(() => {
        let cancelled = false;
        let attempts = 0;
        let timer: ReturnType<typeof setTimeout> | null = null;

        const check = () => {
            aiService.listModels()
                .then((r: any) => {
                    if (cancelled) return;
                    setAvailable(r.data.available);
                    if (r.data.models?.length > 0) {
                        // Use first available model (strip :latest suffix for display)
                        setModelName(r.data.models[0]);
                    }
                })
                .catch(() => {
                    if (cancelled) return;
                    attempts += 1;
                    if (attempts < 3) timer = setTimeout(check, 5000);
                    else setAvailable(false);
                });
        };
        check();
        return () => { cancelled = true; if (timer) clearTimeout(timer); };
    }, []);

    useEffect(() => {
        if (open) {
            setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 50);
            inputRef.current?.focus();
        }
    }, [messages, open]);

    const sendMessage = useCallback(async (text: string = input.trim()) => {
        if (!text || loading) return;
        setInput('');
        const newMessages: Message[] = [...messages, { role: 'user', content: text }];
        setMessages(newMessages);
        setLoading(true);
        setWaitingForFirstToken(true);
        setMessages(prev => [...prev, { role: 'assistant', content: '' }]);

        try {
            await aiService.chatStream(
                newMessages.map((m: Message) => ({ role: m.role, content: m.content })),
                selectedStock?.sym || null,
                modelName,
                (chunk: string) => {
                    setWaitingForFirstToken(false); // first real token arrived
                    setMessages(prev => {
                        const updated = [...prev];
                        const last = updated[updated.length - 1];
                        if (last?.role === 'assistant') {
                            updated[updated.length - 1] = { ...last, content: last.content + chunk };
                        }
                        return updated;
                    });
                },
                () => { setLoading(false); setWaitingForFirstToken(false); },
            );
        } catch (err: any) {
            setMessages(prev => {
                const updated = [...prev];
                updated[updated.length - 1] = {
                    role: 'assistant',
                    content: err.name === 'AbortError' || err.message?.includes('5 นาที')
                        ? 'AI ใช้เวลานานเกินไป — กรุณาลองใหม่'
                        : err.message?.includes('503') || err.message?.includes('ยังไม่พร้อม')
                            ? 'AI assistant ยังไม่พร้อม กรุณาตั้งค่า OLLAMA_URL และติดตั้งโมเดล'
                            : `เกิดข้อผิดพลาด: ${err.message}`,
                    error: true,
                };
                return updated;
            });
            setLoading(false);
            setWaitingForFirstToken(false);
        }
    }, [input, loading, messages, selectedStock, modelName]);

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    };

    if (available === false) return null;

    // ── Floating button (collapsed state) ─────────────────────────────────────
    if (!open) {
        return (
            <button
                onClick={() => setOpen(true)}
                className="fixed z-40 flex items-center gap-2 px-3 py-2 rounded-xl shadow-lg transition-all hover:scale-105 hover:shadow-xl"
                style={{
                    bottom: 52,   // just above StatusBar (~40px)
                    right: 16,
                    background: 'var(--color-accent)',
                    boxShadow: '0 4px 20px rgba(124,92,252,0.45)',
                }}
                title="AI Assistant"
            >
                <Sparkles size={14} className="text-white" />
                <span className="text-white text-[11px] font-semibold">AI</span>
            </button>
        );
    }

    // ── Chat panel (expanded state) ────────────────────────────────────────────
    return (
        <div
            className="fixed z-50 flex flex-col rounded-2xl overflow-hidden animate-slide-up"
            style={{
                bottom: 52,     // above StatusBar
                right: 16,
                width: 320,
                height: 'min(460px, calc(100vh - 120px))',
                background: 'var(--color-panel, #1a1a2e)',
                border: '1px solid var(--color-border)',
                boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
            }}
        >
            {/* Header */}
            <div
                className="flex items-center justify-between px-4 py-2.5 flex-shrink-0"
                style={{ borderBottom: '1px solid var(--color-border)' }}
            >
                <div className="flex items-center gap-2">
                    <Bot size={13} style={{ color: 'var(--color-accent)' }} />
                    <span className="text-xs font-bold" style={{ color: 'var(--color-text)' }}>AI Assistant</span>
                    {selectedStock?.sym && (
                        <span
                            className="text-[10px] px-1.5 py-0.5 rounded font-semibold"
                            style={{ background: 'rgba(124,92,252,0.15)', color: 'var(--color-accent)' }}
                        >
                            {selectedStock.sym}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-0.5">
                    <button
                        onClick={() => setMessages([])}
                        className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-hover)]"
                        style={{ color: 'var(--color-text-sub)' }}
                        title="ล้างการสนทนา"
                    >
                        <RefreshCw size={11} />
                    </button>
                    <button
                        onClick={() => setOpen(false)}
                        className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-hover)]"
                        style={{ color: 'var(--color-text-sub)' }}
                    >
                        <ChevronDown size={13} />
                    </button>
                </div>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3" style={{ minHeight: 0 }}>
                {messages.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full gap-3">
                        <Sparkles size={24} style={{ color: 'var(--color-accent)', opacity: 0.5 }} />
                        <p className="text-[11px] text-center leading-relaxed" style={{ color: 'var(--color-text-sub)' }}>
                            ถามอะไรก็ได้เกี่ยวกับการลงทุน<br />
                            <span style={{ opacity: 0.6 }}>
                                {selectedStock?.sym ? `กำลังดูข้อมูลของ ${selectedStock.sym}` : 'เลือกหุ้นในชาร์ตเพื่อรับบริบท'}
                            </span>
                        </p>
                        <div className="grid grid-cols-2 gap-1.5 w-full">
                            {SUGGESTED_PROMPTS.map((p, i) => (
                                <button
                                    key={i}
                                    onClick={() => sendMessage(p)}
                                    className="text-[10px] px-2 py-1.5 rounded-lg text-left transition-colors hover:bg-[var(--color-hover)]"
                                    style={{
                                        border: '1px solid var(--color-border)',
                                        color: 'var(--color-text-sub)',
                                        background: 'transparent',
                                    }}
                                >
                                    {p}
                                </button>
                            ))}
                        </div>
                    </div>
                ) : (
                    messages.map((msg, i) => (
                        <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            {msg.role === 'assistant' && (
                                <div
                                    className="w-5 h-5 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5"
                                    style={{ background: 'var(--color-accent)' }}
                                >
                                    <Bot size={10} className="text-white" />
                                </div>
                            )}
                            <div
                                className="max-w-[80%] px-3 py-2 text-[11px] leading-relaxed"
                                style={{
                                    background: msg.role === 'user'
                                        ? 'var(--color-accent)'
                                        : msg.error
                                            ? 'rgba(220,38,38,0.12)'
                                            : 'rgba(255,255,255,0.06)',
                                    color: msg.role === 'user' ? '#fff' : msg.error ? 'var(--color-red)' : 'var(--color-text)',
                                    borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                                    border: msg.role === 'assistant' && !msg.error ? '1px solid var(--color-border)' : 'none',
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word',
                                }}
                            >
                                {msg.content || (loading && i === messages.length - 1
                                    ? waitingForFirstToken
                                        ? <span className="text-[10px] opacity-50 animate-pulse">กำลังโหลดโมเดล...</span>
                                        : <span className="animate-pulse opacity-60">▌</span>
                                    : null
                                )}
                            </div>
                        </div>
                    ))
                )}
                <div ref={bottomRef} />
            </div>

            {/* Input */}
            <div className="px-3 pb-3 pt-2 flex-shrink-0" style={{ borderTop: '1px solid var(--color-border)' }}>
                <div
                    className="flex items-center gap-2 rounded-xl px-3 py-2"
                    style={{
                        background: 'rgba(255,255,255,0.05)',
                        border: '1px solid var(--color-border)',
                    }}
                >
                    <input
                        ref={inputRef}
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={handleKeyDown}
                        disabled={loading}
                        placeholder="ถามเกี่ยวกับการลงทุน..."
                        className="flex-1 bg-transparent text-[11px] outline-none placeholder:opacity-40"
                        style={{ color: 'var(--color-text)' }}
                    />
                    <button
                        onClick={() => sendMessage()}
                        disabled={loading || !input.trim()}
                        className="w-6 h-6 rounded-full flex items-center justify-center transition-all disabled:opacity-30"
                        style={{ background: input.trim() ? 'var(--color-accent)' : 'var(--color-hover)' }}
                    >
                        <Send size={10} className="text-white" />
                    </button>
                </div>
                <p className="text-[9px] mt-1 text-center" style={{ color: 'var(--color-text-sub)', opacity: 0.4 }}>
                    {modelName.replace(':latest', '')} · ไม่ใช่คำแนะนำทางการเงิน
                </p>
            </div>
        </div>
    );
}
