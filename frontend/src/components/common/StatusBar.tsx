import { useEffect, useState } from 'react';

export default function StatusBar() {
    const [timeStr, setTimeStr] = useState<string>('');

    useEffect(() => {
        const updateTime = () => {
            const now = new Date();
            setTimeStr(now.toLocaleTimeString('en-GB', { hour12: false }));
        };

        updateTime();
        const interval = setInterval(updateTime, 1000);
        return () => clearInterval(interval);
    }, []);

    return (
        <div
            className="panel border-t flex items-center justify-between px-4 py-1"
            style={{ borderTopWidth: 1, borderTopStyle: 'solid' }}
        >
            <div className="flex items-center gap-4">
                <span className="text-xs" style={{ color: 'var(--color-green)' }}>● Live</span>
                <span className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                    อัปเดตล่าสุด: {timeStr}
                </span>
            </div>
            <div className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                ShotockViz v0.1 · Data: yfinance + Finnhub · Delayed 15min
            </div>
        </div>
    );
}
