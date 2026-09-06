import { useEffect, useRef, useState } from 'react';
import { Link } from '@tanstack/react-router';
import toast from 'react-hot-toast';
import { Settings as SettingsIcon, Palette, Bell, Moon, Sun, BellOff } from 'lucide-react';
import useAppStore from '@/store/appStore';
import authService from '@/services/authService';
import api from '@/services/api';
import { getCurrentSection } from '@/utils/scrollspy';
import { didClearAuthSession } from '@/services/apiErrorHandler';

// bd:shotockviz-06z.1 — restates `models.schemas.MIN_/MAX_GAP_MIN_PCT`
// (backend/models/schemas.py), the ONE place these bounds are actually
// enforced (api/routes/settings.py PATCH /settings/trader). Same
// client/server duplication risk `utils/concentrationLimit.ts` already
// documents for its own MIN/MAX constants — restated here rather than
// invented, and validated client-side only so a bad value never round-trips
// before the server would reject it anyway.
const MIN_GAP_MIN_PCT = 0.1;
const MAX_GAP_MIN_PCT = 50.0;

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
    // bd:shotockviz-06z.1 — `''` means "unset" (matches `users.gap_min_pct`
    // NULL, i.e. no filter on the 20:00 ICT gap digest — see
    // workers/gap_list_digest.py). Deliberately never defaulted to a number
    // here: an empty input reads back as `null` on save, not `0` or any
    // other invented starting value.
    const [gapMinPct, setGapMinPct] = useState('');
    const [gapMinPctError, setGapMinPctError] = useState<string | null>(null);
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
        // bd:shotockviz-06z.1 — a separate GET, a separate endpoint
        // (api/routes/settings.py, not auth.py — see that module's
        // docstring for why), so a failure here degrades ONLY the gap
        // threshold field, never blocks telegram settings from loading.
        //
        // bd:shotockviz-tjh — decorative hydrate, same as
        // ConcentrationLimitPanel's identical GET: the field already
        // degrades to "" (unset) below on any failure, so
        // `skipAuthClearOn401` keeps a 401 here from logging the trader out
        // of the Settings page it's decorating. The PATCH in handleSave
        // below (Save button — a real user action) is left unflagged: a
        // genuinely expired session must still log them out on submit.
        api.get('/settings/trader', { skipAuthClearOn401: true })
            .then((res) => {
                if (cancelled) return;
                const value = res.data?.gap_min_pct;
                setGapMinPct(value == null ? '' : String(value));
            })
            .catch(() => { /* leave as "" (unset) — never guess a number */ });
        return () => { cancelled = true; };
    }, []);

    const handleSave = async () => {
        setGapMinPctError(null);
        let gapMinPctPayload: number | null = null;
        if (gapMinPct.trim() !== '') {
            const parsed = Number(gapMinPct);
            if (!Number.isFinite(parsed) || parsed < MIN_GAP_MIN_PCT || parsed > MAX_GAP_MIN_PCT) {
                setGapMinPctError(`ระบุตัวเลข ${MIN_GAP_MIN_PCT}-${MAX_GAP_MIN_PCT} หรือเว้นว่างไว้เพื่อไม่ตั้งเกณฑ์`);
                return;
            }
            gapMinPctPayload = parsed;
        }

        setIsSaving(true);
        // bd:shotockviz-06z.1 — two independent settings, two independent
        // endpoints (telegram_chat_id has a real side effect — a live test
        // message — gap_min_pct never does), so a failure in one must not
        // hide whether the other one succeeded. Promise.allSettled, not
        // Promise.all: an unhandled rejection from the second call must
        // never suppress the first call's own success/toast handling.
        const [telegramResult, gapResult] = await Promise.allSettled([
            authService.updateSettings({ telegram_chat_id: telegramChatId || null }),
            api.patch('/settings/trader', { gap_min_pct: gapMinPctPayload }),
        ]);

        if (telegramResult.status === 'fulfilled') {
            toast.success(
                telegramChatId
                    ? 'บันทึกแล้ว — ส่งข้อความทดสอบไปที่ Telegram สำเร็จ ✅'
                    : 'บันทึกการตั้งค่าแล้ว'
            );
        }
        // A rejected telegramResult already toasted via the axios response
        // interceptor (api.ts) using the backend's own failure reason —
        // never duplicated here.
        if (gapResult.status === 'rejected') {
            // The interceptor also toasts this (e.g. a 422 out-of-range
            // value), but the gap field gets its OWN inline error too:
            // bd:shotockviz-06z.1 must never let this field read as saved
            // when the request the trader just made was rejected.
            //
            // bd:shotockviz-2qw — except when the rejection WAS the logout.
            // PATCH is deliberately not flagged `skipAuthClearOn401`
            // (bd:shotockviz-tjh), so a 401 here has already cleared the
            // session; "try again" on top of that points the trader at a form
            // they no longer have a session for.
            if (!didClearAuthSession(gapResult.reason)) {
                setGapMinPctError('บันทึกเกณฑ์ Gap ไม่สำเร็จ ลองใหม่อีกครั้ง');
            }
        }

        setIsSaving(false);
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

                            {/* bd:shotockviz-06z.1 — the 20:00 ICT overnight-gap digest
                                (workers/gap_list_digest.py) has no invented magnitude
                                cutoff; this is where the trader states his own, if he
                                wants one at all. Empty = unset = every symbol with a
                                fresh quote is listed, exactly as bd:shotockviz-06z
                                originally shipped it — never a guessed starting number. */}
                            <div className="max-w-[420px] mb-4">
                                <label htmlFor="settings-gap-min-pct" className="text-[10px] uppercase tracking-wider mb-1.5 block font-bold" style={{ color: 'var(--color-text-sub)' }}>
                                    เกณฑ์ขั้นต่ำ Gap พรีมาร์เก็ต (%)
                                </label>
                                <input
                                    id="settings-gap-min-pct"
                                    className="input-field mono"
                                    type="number"
                                    inputMode="decimal"
                                    step="0.1"
                                    min={MIN_GAP_MIN_PCT}
                                    max={MAX_GAP_MIN_PCT}
                                    placeholder="ไม่ตั้งเกณฑ์ (แสดงทุกตัว, สูงสุด 20)"
                                    value={gapMinPct}
                                    onChange={(e) => setGapMinPct(e.target.value)}
                                    disabled={isLoadingSettings || isSaving}
                                    aria-describedby="settings-gap-min-pct-hint"
                                />
                                <p id="settings-gap-min-pct-hint" className="mt-2 text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                    สรุป Gap ข้ามคืนทาง Telegram ทุกวัน 20:00 น. จะแสดงเฉพาะหุ้น/กองทุนที่เปลี่ยนแปลงอย่างน้อยเท่านี้ —
                                    เว้นว่างไว้เพื่อแสดงทุกตัวในพอร์ต/watchlist (สูงสุด 20 รายการต่อข้อความ)
                                </p>
                                {gapMinPctError && (
                                    <p role="alert" className="mt-1 text-[11px]" style={{ color: 'var(--color-red)' }}>
                                        {gapMinPctError}
                                    </p>
                                )}
                            </div>

                            <div className="max-w-[420px] rounded-xl p-3 flex items-start gap-2" style={{ border: '1px dashed var(--color-border-strong)' }}>
                                <BellOff size={12} strokeWidth={2} className="mt-0.5 shrink-0" aria-hidden="true" style={{ color: 'var(--color-text-sub)' }} />
                                <span className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>
                                    การแจ้งเตือนเพิ่มเติม — Quiet hours · ช่องทางอื่น (เร็วๆ นี้)
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
