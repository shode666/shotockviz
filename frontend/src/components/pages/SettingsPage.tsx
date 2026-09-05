import { useEffect, useRef, useState } from 'react';
import { Link } from '@tanstack/react-router';
import toast from 'react-hot-toast';
import { Settings as SettingsIcon, Palette, Bell, Moon, Sun, BellOff } from 'lucide-react';
import useAppStore from '@/store/appStore';
import authService from '@/services/authService';
import { getCurrentSection } from '@/utils/scrollspy';

const CATEGORIES = [
    { key: 'general', href: '#general', label: 'General', Icon: Palette },
    { key: 'notification', href: '#notification', label: 'Notification', Icon: Bell },
];

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
    return (
        <section id={id} className="panel border rounded-2xl p-4 mb-4 scroll-mt-16" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
            <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--color-text-sub)' }}>{title}</div>
            {children}
        </section>
    );
}

export default function SettingsPage() {
    // bd:ux-2026-09 user-reported regression investigation — was toggleTheme,
    // which just flips dark<->light regardless of which card was clicked;
    // clicking the theme you're already ON silently landed you on the OTHER
    // one. setTheme(key) selects the clicked card's theme explicitly instead
    // (appStore.ts).
    const { theme, setTheme } = useAppStore();
    // bd:features-2026-09 slice 3 — wired to GET/PATCH /api/v1/auth/settings.
    // PATCH sends a real Telegram test message server-side (D2); a 422 here
    // means the chat id is wrong or the user never messaged the bot — the
    // axios error interceptor (api.ts) already surfaces that as a toast
    // using the backend's Thai error message, so the local catch below
    // only needs to reset the saving state, not duplicate the toast.
    const [telegramChatId, setTelegramChatId] = useState('');
    const [isLoadingSettings, setIsLoadingSettings] = useState(true);
    const [isSaving, setIsSaving] = useState(false);

    // Scrollspy — aria-current follows the section actually in view instead
    // of a hardcoded first-item default.
    const scrollContainerRef = useRef<HTMLDivElement>(null);
    const [activeIndex, setActiveIndex] = useState(0);

    useEffect(() => {
        const container = scrollContainerRef.current;
        if (!container) return;

        // bd:ui-honesty-2026-09 F2 fix — offsetTop is relative to offsetParent
        // (here <body>, not the scroll container), so it was in the wrong
        // coordinate frame vs container.scrollTop. Measured in-page: general
        // top (container-relative) ~78, notification ~244.9, but max
        // container.scrollTop is only 207.5 — the last section can never
        // reach the container's own top, so a plain "top <= scrollTop"
        // compare could never select it either. Fix: compute each section's
        // top relative to the container via getBoundingClientRect(), and
        // compare against scrollTop + an activation offset
        // (clientHeight * 0.3) so the probe point sits below the visible
        // top instead of exactly at it. With the measured numbers this
        // resolves both ends: top (scrollTop=0) -> probe 105 >= general 78
        // -> index 0; bottom (scrollTop=207.5) -> probe 312.5 >=
        // notification 244.9 -> index 1.
        const updateActiveSection = () => {
            const containerRect = container.getBoundingClientRect();
            const activationOffset = container.clientHeight * 0.3;
            const tops = CATEGORIES.map(({ href }) => {
                const el = container.querySelector<HTMLElement>(href);
                // bd:ui-honesty-2026-09 Chris Medium #4 — a missing section must
                // never win as "current". `0` always satisfies `scrollY >= top`,
                // so a future CATEGORIES entry whose <Section> hasn't shipped yet
                // would silently mis-highlight. Infinity can never be reached.
                if (!el) return Number.POSITIVE_INFINITY;
                const elRect = el.getBoundingClientRect();
                return elRect.top - containerRect.top + container.scrollTop;
            });
            setActiveIndex(getCurrentSection(tops, container.scrollTop + activationOffset));
        };

        updateActiveSection();
        container.addEventListener('scroll', updateActiveSection, { passive: true });
        // Section tops shift with layout (font load, window resize) — recompute then too.
        window.addEventListener('resize', updateActiveSection);
        return () => {
            container.removeEventListener('scroll', updateActiveSection);
            window.removeEventListener('resize', updateActiveSection);
        };
    }, []);

    useEffect(() => {
        let cancelled = false;
        authService.getSettings()
            .then(({ data }) => {
                if (!cancelled) setTelegramChatId(data.telegram_chat_id ?? '');
            })
            .catch(() => { /* silent — interceptor's 401/404 handling already applies */ })
            .finally(() => { if (!cancelled) setIsLoadingSettings(false); });
        return () => { cancelled = true; };
    }, []);

    const handleSave = async () => {
        setIsSaving(true);
        try {
            await authService.updateSettings({ telegram_chat_id: telegramChatId || null });
            toast.success(
                telegramChatId
                    ? 'บันทึกแล้ว — ส่งข้อความทดสอบไปที่ Telegram สำเร็จ ✅'
                    : 'บันทึกการตั้งค่าแล้ว'
            );
        } catch {
            // Error toast already shown by the axios response interceptor
            // (api.ts) using the backend's clear failure reason.
        } finally {
            setIsSaving(false);
        }
    };

    return (
        <div ref={scrollContainerRef} className="flex-1 overflow-auto p-6" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-4xl mx-auto animate-fade-in">

                <div className="mb-5">
                    <h2 className="text-base font-bold flex items-center gap-2">
                        <SettingsIcon size={16} />
                        Settings
                    </h2>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-sub)' }}>ตั้งค่าการแสดงผล กราฟ และการแจ้งเตือน</p>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-4">
                    {/* Side nav — anchor jump list; "General" shown as entry point per mock */}
                    <nav aria-label="หมวดตั้งค่า" className="panel border rounded-2xl p-3 flex flex-row md:flex-col gap-1 h-fit" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        {CATEGORIES.map(({ key, href, label, Icon }, i) => (
                            <a
                                key={key}
                                href={href}
                                aria-current={i === activeIndex ? 'true' : undefined}
                                className="flex items-center gap-2 px-3 py-2.5 text-xs rounded-xl font-medium transition-all"
                                style={{
                                    background: i === activeIndex ? 'var(--surface-3)' : 'transparent',
                                    color: i === activeIndex ? 'var(--color-accent-text-raised)' : 'var(--color-text-sub)',
                                }}
                                onMouseEnter={(e) => { if (i !== activeIndex) e.currentTarget.style.background = 'var(--surface-2)' }}
                                onMouseLeave={(e) => { if (i !== activeIndex) e.currentTarget.style.background = 'transparent' }}
                            >
                                <Icon size={13} />
                                {label}
                            </a>
                        ))}
                    </nav>

                    <div>
                        <Section id="general" title="Theme">
                            <div className="grid grid-cols-2 gap-3 max-w-[360px]">
                                {[
                                    { key: 'dark', label: 'Dark', Icon: Moon, desc: 'Easy on eyes' },
                                    { key: 'light', label: 'Light', Icon: Sun, desc: 'Bright mode' },
                                ].map(({ key, label, Icon, desc }) => {
                                    const active = theme === key;
                                    return (
                                        <button
                                            key={key}
                                            onClick={() => setTheme(key)}
                                            aria-pressed={active}
                                            className="flex flex-col items-center justify-center p-4 rounded-xl transition-all"
                                            style={{
                                                border: active ? '1.5px solid var(--color-accent)' : '1px solid var(--color-border)',
                                                background: active ? 'var(--color-accent-glow)' : 'var(--surface-1)',
                                            }}
                                        >
                                            <Icon size={18} className="mb-2" style={{ color: active ? 'var(--color-accent-text)' : 'var(--color-text-sub)' }} />
                                            <span className="text-xs font-semibold" style={{ color: active ? 'var(--color-accent-text)' : 'var(--color-text)' }}>{label}</span>
                                            <span className="text-[9px] mt-0.5" style={{ color: 'var(--color-text-sub)' }}>{desc}</span>
                                        </button>
                                    );
                                })}
                            </div>
                        </Section>

                        <Section id="notification" title="Notification">
                            <div className="max-w-[420px] mb-4">
                                <label htmlFor="settings-telegram" className="text-[10px] uppercase tracking-wider mb-1.5 block font-bold" style={{ color: 'var(--color-text-sub)' }}>
                                    Telegram Chat ID
                                </label>
                                <input
                                    id="settings-telegram"
                                    className="input-field mono"
                                    type="text"
                                    inputMode="numeric"
                                    placeholder="เช่น 128845067"
                                    value={telegramChatId}
                                    onChange={(e) => setTelegramChatId(e.target.value)}
                                    disabled={isLoadingSettings || isSaving}
                                    aria-describedby="settings-telegram-hint"
                                />
                                <p id="settings-telegram-hint" className="mt-2 text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                    คุยกับ @ShotockVizBot แล้วพิมพ์ /start เพื่อรับ chat id — ใช้รับ alert ผ่าน Telegram
                                </p>
                            </div>
                            <div className="max-w-[420px] rounded-xl p-3 flex items-start gap-2" style={{ border: '1px dashed var(--color-border-strong)' }}>
                                <BellOff size={12} strokeWidth={2} className="mt-0.5 shrink-0" aria-hidden="true" style={{ color: 'var(--color-text-sub)' }} />
                                <span className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>
                                    การแจ้งเตือนเพิ่มเติม — Quiet hours · สรุปรายวัน · ช่องทางอื่น (เร็วๆ นี้)
                                </span>
                            </div>
                        </Section>

                        <div className="flex justify-end gap-2 mb-5">
                            <Link to="/dashboard" className="btn-outline px-5 py-2 text-xs">ยกเลิก</Link>
                            <button
                                onClick={handleSave}
                                disabled={isSaving}
                                className="btn-accent px-5 py-2 text-xs disabled:opacity-60"
                            >
                                {isSaving ? 'กำลังบันทึก...' : 'บันทึก'}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
