import { useState } from 'react';
import { Link } from '@tanstack/react-router';
import toast from 'react-hot-toast';
import { Settings as SettingsIcon, Palette, TrendingUp, Bell, Moon, Sun, BellOff } from 'lucide-react';
import useAppStore from '@/store/appStore';

const CATEGORIES = [
    { key: 'general', href: '#general', label: 'General', Icon: Palette },
    { key: 'chart', href: '#chart', label: 'Chart', Icon: TrendingUp },
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
    const { theme, toggleTheme } = useAppStore();
    // Telegram chat id — UI only, local state (bd:ux-2026-09). Backend wiring
    // for actually saving/verifying this id belongs to the features-2026-09 bd.
    const [telegramChatId, setTelegramChatId] = useState('');

    const handleSave = () => {
        toast.success('บันทึกการตั้งค่าแล้ว (แสดงผลเท่านั้น — การเชื่อม Telegram จริงยังไม่เปิดใช้งาน)');
    };

    return (
        <div className="flex-1 overflow-auto p-6" style={{ background: 'var(--color-bg)' }}>
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
                                aria-current={i === 0 ? 'true' : undefined}
                                className="flex items-center gap-2 px-3 py-2.5 text-xs rounded-xl font-medium transition-all"
                                style={{
                                    background: i === 0 ? 'var(--surface-3)' : 'transparent',
                                    color: i === 0 ? 'var(--color-accent-text-strong)' : 'var(--color-text-sub)',
                                }}
                                onMouseEnter={(e) => { if (i !== 0) e.currentTarget.style.background = 'var(--surface-2)' }}
                                onMouseLeave={(e) => { if (i !== 0) e.currentTarget.style.background = 'transparent' }}
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
                                            onClick={toggleTheme}
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

                        <Section id="timezone" title="Timezone">
                            <div className="max-w-[420px]">
                                <label htmlFor="settings-tz" className="sr-only">Timezone</label>
                                <select id="settings-tz" className="input-field glass-select" defaultValue="Asia/Bangkok">
                                    <option value="Asia/Bangkok">Asia/Bangkok (UTC+7) — ไทย</option>
                                    <option value="America/New_York">America/New_York (UTC−5) — US EST</option>
                                    <option value="Europe/London">Europe/London (UTC+0) — UK</option>
                                    <option value="UTC">UTC (UTC+0)</option>
                                </select>
                                <p className="mt-2 text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                    ShotockViz แสดงเวลาตาม timezone ของตลาดหุ้นโดยอัตโนมัติ
                                </p>
                            </div>
                        </Section>

                        <Section id="chart" title="Chart Defaults">
                            <div className="flex flex-col gap-2.5 max-w-[420px]">
                                {[
                                    { id: 'settings-tf', label: 'Default Timeframe', options: ['1D', '1W', '1M', '1h', '4h'] },
                                    { id: 'settings-ct', label: 'Chart Type', options: ['Candlestick', 'Line', 'Area'] },
                                ].map(({ id, label, options }) => (
                                    <div key={id}>
                                        <label htmlFor={id} className="text-[10px] mb-1.5 block" style={{ color: 'var(--color-text-sub)' }}>{label}</label>
                                        <select id={id} className="input-field glass-select">
                                            {options.map((o) => <option key={o}>{o}</option>)}
                                        </select>
                                    </div>
                                ))}
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
                            <button onClick={handleSave} className="btn-accent px-5 py-2 text-xs">บันทึก</button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
