import { Bell, Zap, ArrowRight } from 'lucide-react';
import { displaySymbol } from '@/utils/formatters';

interface AlertNearTargetItemProps {
    symbol: string;
    target: number;
    current: number;
    diffPct: number;
    condition: string;
}

function AlertNearTarget({ symbol, target, current, diffPct, condition }: AlertNearTargetItemProps) {
    return (
        <div
            className="flex items-center gap-2 px-3 py-2 rounded-xl border"
            style={{ borderColor: '#f59e0b44', background: 'rgba(245,158,11,0.06)' }}
        >
            <Bell size={11} className="flex-shrink-0" style={{ color: '#f59e0b' }} />
            <div className="flex-1 min-w-0">
                <span className="font-bold text-xs">{displaySymbol(symbol)}</span>
                <span className="text-[10px] ml-1.5" style={{ color: 'var(--color-text-sub)' }}>
                    {condition} {target.toFixed(2)} · ปัจจุบัน {current.toFixed(2)}
                </span>
            </div>
            <span className="text-[10px] font-bold shrink-0" style={{ color: '#f59e0b' }}>
                ±{diffPct.toFixed(1)}%
            </span>
        </div>
    );
}

interface AlertsNearTargetProps {
    isAuthenticated: boolean;
    alertCount: number;
    alertsNear: Array<{
        symbol: string;
        target: number;
        current: number;
        diff_pct: number;
        condition: string;
    }>;
    onNavigateToAlerts: () => void;
    onNavigateToLogin: () => void;
}

export function AlertsNearTarget({
    isAuthenticated,
    alertCount,
    alertsNear,
    onNavigateToAlerts,
    onNavigateToLogin,
}: AlertsNearTargetProps) {
    return (
        <div
            className="md:col-span-3 xl:col-span-2 panel rounded-xl border p-4 flex flex-col gap-2"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}
        >
            <div className="flex items-center justify-between">
                <span
                    className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5"
                    style={{ color: 'var(--color-text-sub)' }}
                >
                    <Bell size={11} /> Alerts
                </span>
                <button
                    onClick={onNavigateToAlerts}
                    className="text-[10px] font-medium transition-colors hover:opacity-70 flex items-center gap-0.5"
                    style={{ color: 'var(--color-accent)' }}
                >
                    จัดการ <ArrowRight size={12} strokeWidth={2} aria-hidden="true" />
                </button>
            </div>

            {!isAuthenticated ? (
                <p className="text-xs py-3 text-center" style={{ color: 'var(--color-text-sub)' }}>
                    Login เพื่อดู Alert
                </p>
            ) : (
                <div className="flex items-start gap-6">
                    <div className="flex items-center gap-2 shrink-0">
                        <Zap size={18} style={{ color: 'var(--color-accent)' }} />
                        <span className="text-xl font-bold">{alertCount}</span>
                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                            active
                        </span>
                    </div>

                    <div className="flex-1 min-w-0">
                        {alertsNear.length > 0 ? (
                            <div className="space-y-1.5">
                                <p className="text-[10px] font-semibold mb-1 flex items-center gap-1" style={{ color: '#f59e0b' }}>
                                    <Zap size={11} strokeWidth={2} aria-hidden="true" /> ใกล้ถึง target:
                                </p>
                                {alertsNear.map((a: any, i: number) => (
                                    <AlertNearTarget
                                        key={`${a.symbol}-${a.condition}`}
                                        symbol={a.symbol}
                                        target={a.target}
                                        current={a.current}
                                        diffPct={a.diff_pct}
                                        condition={a.condition}
                                    />
                                ))}
                            </div>
                        ) : alertCount === 0 ? (
                            <div className="flex items-center gap-3">
                                <Bell size={16} style={{ color: 'var(--color-text-sub)' }} />
                                <div>
                                    <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                                        ยังไม่มี Alert
                                    </p>
                                    <button
                                        onClick={onNavigateToAlerts}
                                        className="btn-accent text-[10px] px-3 py-1 mt-1.5"
                                    >
                                        + สร้าง Alert
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <p className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                ราคายังห่าง target ทุก alert
                            </p>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
