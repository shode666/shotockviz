/**
 * Volume Profile (Visible Range — VPVR) overlay.
 *
 * Renders horizontal volume bars on the right side of the chart.
 * - Point of Control (POC) = price level with highest volume → gold bar
 * - Value Area (70% of total volume) → lighter color
 *
 * This is a canvas overlay that syncs with the TradingView chart coordinate system.
 */
import { useEffect, useRef, useMemo, useCallback } from 'react';

interface Bar {
    time: number | string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

interface VolumeProfileProps {
    bars: Bar[];
    chartHeight: number;
    chartWidth: number;
    priceToY: (price: number) => number | null;  // chart coordinate converter
    darkMode?: boolean;
    bucketCount?: number;  // number of price levels (default: 80)
    widthPct?: number;     // max width as % of chart (default: 15)
}

interface ProfileLevel {
    priceMin: number;
    priceMax: number;
    priceMid: number;
    volume: number;
    isPOC: boolean;
    isValueArea: boolean;
}

function computeProfile(bars: Bar[], bucketCount: number): ProfileLevel[] {
    if (bars.length === 0) return [];

    // Find price range
    let highest = -Infinity;
    let lowest = Infinity;
    for (const b of bars) {
        if (b.high > highest) highest = b.high;
        if (b.low < lowest) lowest = b.low;
    }

    if (highest <= lowest) return [];

    const range = highest - lowest;
    const step = range / bucketCount;
    const buckets = new Array(bucketCount).fill(0);

    // Distribute volume across price buckets
    for (const b of bars) {
        const vol = b.volume || 0;
        if (vol <= 0) continue;

        // Each bar contributes volume to all buckets it spans
        const barLow = b.low;
        const barHigh = b.high;
        const startBucket = Math.max(0, Math.floor((barLow - lowest) / step));
        const endBucket = Math.min(bucketCount - 1, Math.floor((barHigh - lowest) / step));

        const spanBuckets = endBucket - startBucket + 1;
        const volPerBucket = vol / spanBuckets;

        for (let i = startBucket; i <= endBucket; i++) {
            buckets[i] += volPerBucket;
        }
    }

    // Find POC (max volume level)
    let maxVol = 0;
    let pocIdx = 0;
    for (let i = 0; i < bucketCount; i++) {
        if (buckets[i] > maxVol) {
            maxVol = buckets[i];
            pocIdx = i;
        }
    }

    // Calculate Value Area (70% of total volume, expanding from POC)
    const totalVol = buckets.reduce((sum, v) => sum + v, 0);
    const targetVol = totalVol * 0.7;
    const inValueArea = new Set<number>();
    inValueArea.add(pocIdx);
    let accumulatedVol = buckets[pocIdx];
    let upper = pocIdx;
    let lower = pocIdx;

    while (accumulatedVol < targetVol && (upper < bucketCount - 1 || lower > 0)) {
        const aboveVol = upper < bucketCount - 1 ? buckets[upper + 1] : 0;
        const belowVol = lower > 0 ? buckets[lower - 1] : 0;

        if (aboveVol >= belowVol && upper < bucketCount - 1) {
            upper++;
            accumulatedVol += buckets[upper];
            inValueArea.add(upper);
        } else if (lower > 0) {
            lower--;
            accumulatedVol += buckets[lower];
            inValueArea.add(lower);
        } else {
            break;
        }
    }

    // Build levels
    return buckets.map((vol, i) => ({
        priceMin: lowest + i * step,
        priceMax: lowest + (i + 1) * step,
        priceMid: lowest + (i + 0.5) * step,
        volume: vol,
        isPOC: i === pocIdx,
        isValueArea: inValueArea.has(i),
    }));
}

export default function VolumeProfile({
    bars,
    chartHeight,
    chartWidth,
    priceToY,
    darkMode = true,
    bucketCount = 80,
    widthPct = 15,
}: VolumeProfileProps) {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    const profile = useMemo(
        () => computeProfile(bars, bucketCount),
        [bars, bucketCount]
    );

    const draw = useCallback(() => {
        const canvas = canvasRef.current;
        if (!canvas || profile.length === 0) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const dpr = window.devicePixelRatio || 1;
        canvas.width = chartWidth * dpr;
        canvas.height = chartHeight * dpr;
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, chartWidth, chartHeight);

        // Find max volume for normalization
        const maxVol = Math.max(...profile.map(l => l.volume));
        if (maxVol <= 0) return;

        const maxBarWidth = chartWidth * (widthPct / 100);
        const rightMargin = 60; // space for price scale

        for (const level of profile) {
            if (level.volume <= 0) continue;

            const y1 = priceToY(level.priceMax);
            const y2 = priceToY(level.priceMin);
            if (y1 === null || y2 === null) continue;

            const barHeight = Math.max(1, Math.abs(y2 - y1) - 0.5);
            const barWidth = (level.volume / maxVol) * maxBarWidth;
            const x = chartWidth - rightMargin - barWidth;
            const y = Math.min(y1, y2);

            // Color based on type
            if (level.isPOC) {
                ctx.fillStyle = darkMode
                    ? 'rgba(251, 191, 36, 0.65)'   // gold
                    : 'rgba(217, 119, 6, 0.60)';
            } else if (level.isValueArea) {
                ctx.fillStyle = darkMode
                    ? 'rgba(99, 102, 241, 0.35)'    // indigo
                    : 'rgba(99, 102, 241, 0.25)';
            } else {
                ctx.fillStyle = darkMode
                    ? 'rgba(156, 163, 175, 0.15)'   // gray
                    : 'rgba(107, 114, 128, 0.12)';
            }

            ctx.fillRect(x, y, barWidth, barHeight);
        }
    }, [profile, chartHeight, chartWidth, priceToY, darkMode, widthPct]);

    useEffect(() => {
        draw();
    }, [draw]);

    return (
        <canvas
            ref={canvasRef}
            className="absolute inset-0 pointer-events-none"
            style={{ width: chartWidth, height: chartHeight }}
        />
    );
}

export { computeProfile };
export type { ProfileLevel, VolumeProfileProps };
