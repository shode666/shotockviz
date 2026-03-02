import { X, Moon, Sun, Globe, Palette } from 'lucide-react';
import useAppStore from '@/store/appStore';

export default function SettingsModal({ isOpen, onClose }) {
    const { theme, toggleTheme } = useAppStore();

    if (!isOpen) return null;

    return (
        <div
            className="glass-backdrop fixed inset-0 z-50 flex items-center justify-center p-4"
            onClick={(e) => e.currentTarget === e.target && onClose()}
        >
            <div className="glass-panel w-full max-w-xl flex flex-col max-h-[82vh] glass-slide-up" style={{ borderRadius: 'var(--radius-glass-lg)' }}>

                {/* Header */}
                <div
                    className="flex items-center justify-between px-6 py-4 glass-divider"
                >
                    <div>
                        <h2 className="text-sm font-bold" style={{ color: 'var(--color-text)' }}>Settings</h2>
                        <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-sub)' }}>ตั้งค่าการแสดงผลและภูมิภาค</p>
                    </div>
                    <button
                        onClick={onClose}
                        className="p-2 rounded-xl transition-all"
                        style={{ color: 'var(--color-text-sub)' }}
                        onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-hover)')}
                        onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                    >
                        <X size={16} />
                    </button>
                </div>

                <div className="flex flex-1 overflow-hidden">
                    {/* Sidebar */}
                    <div
                        className="w-36 p-3 flex flex-col gap-1 overflow-y-auto flex-shrink-0"
                        style={{
                            borderRight: 'var(--glass-divider)',
                            background: 'rgba(0,0,0,0.07)',
                        }}
                    >
                        {[
                            { key: 'appearance', label: 'Appearance', Icon: Palette },
                            { key: 'locale',     label: 'Region',     Icon: Globe   },
                        ].map(({ key, label, Icon }) => {
                            const active = key === 'appearance';
                            return (
                                <button
                                    key={key}
                                    className="w-full flex items-center gap-2 px-3 py-2.5 text-xs rounded-xl font-medium transition-all text-left"
                                    style={{
                                        background: active ? 'var(--color-accent-glow)' : 'transparent',
                                        color:      active ? 'var(--color-accent)'      : 'var(--color-text-sub)',
                                        border:     active ? '1px solid rgba(124,92,252,0.20)' : '1px solid transparent',
                                    }}
                                >
                                    <Icon size={13} />
                                    {label}
                                </button>
                            );
                        })}
                    </div>

                    {/* Content */}
                    <div className="flex-1 p-6 overflow-y-auto">
                        <div className="space-y-7">

                            {/* Theme picker */}
                            <section>
                                <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--color-text-sub)' }}>
                                    Theme
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    {[
                                        { key: 'dark',  label: 'Dark',  Icon: Moon, desc: 'Easy on eyes' },
                                        { key: 'light', label: 'Light', Icon: Sun,  desc: 'Bright mode'  },
                                    ].map(({ key, label, Icon, desc }) => {
                                        const active = theme === key;
                                        return (
                                            <button
                                                key={key}
                                                onClick={toggleTheme}
                                                className="flex flex-col items-center justify-center p-4 rounded-xl transition-all"
                                                style={{
                                                    border: active ? '1.5px solid var(--color-accent)' : '1px solid var(--color-border)',
                                                    background: active ? 'var(--color-accent-glow)' : 'var(--color-hover)',
                                                    boxShadow: active ? '0 0 0 3px rgba(124,92,252,0.08)' : 'none',
                                                }}
                                            >
                                                <Icon size={20} className="mb-2" style={{ color: active ? 'var(--color-accent)' : 'var(--color-text-sub)' }} />
                                                <span className="text-xs font-semibold" style={{ color: active ? 'var(--color-accent)' : 'var(--color-text)' }}>{label}</span>
                                                <span className="text-[9px] mt-0.5" style={{ color: 'var(--color-text-sub)' }}>{desc}</span>
                                            </button>
                                        );
                                    })}
                                </div>
                            </section>

                            {/* Timezone */}
                            <section>
                                <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--color-text-sub)' }}>
                                    Timezone
                                </div>
                                <select className="input-field glass-select" defaultValue="Asia/Bangkok">
                                    <option value="Asia/Bangkok">Asia/Bangkok (UTC+7) — ไทย</option>
                                    <option value="America/New_York">America/New_York (UTC-5) — US EST</option>
                                    <option value="Europe/London">Europe/London (UTC+0) — UK</option>
                                    <option value="UTC">UTC (UTC+0)</option>
                                </select>
                                <p className="mt-2 text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                    ShotockViz แสดงเวลาตาม timezone ของตลาดหุ้นโดยอัตโนมัติ
                                </p>
                            </section>

                            {/* Chart defaults */}
                            <section>
                                <div className="text-[10px] font-semibold uppercase tracking-widest mb-3" style={{ color: 'var(--color-text-sub)' }}>
                                    Chart Defaults
                                </div>
                                <div className="space-y-2.5">
                                    {[
                                        { label: 'Default Timeframe', options: ['1D', '1W', '1M', '1h', '4h'] },
                                        { label: 'Chart Type',        options: ['Candlestick', 'Line', 'Area'] },
                                    ].map(({ label, options }) => (
                                        <div key={label}>
                                            <div className="text-[10px] mb-1.5" style={{ color: 'var(--color-text-sub)' }}>{label}</div>
                                            <select className="input-field glass-select">
                                                {options.map(o => <option key={o}>{o}</option>)}
                                            </select>
                                        </div>
                                    ))}
                                </div>
                            </section>

                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div
                    className="flex justify-end gap-2 px-6 py-4 glass-divider"
                >
                    <button onClick={onClose} className="btn-outline px-5 py-2 text-xs">ปิด</button>
                    <button className="btn-accent px-5 py-2 text-xs">บันทึก</button>
                </div>
            </div>
        </div>
    );
}
