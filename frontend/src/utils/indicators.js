// Technical Indicators Calculation Utility

export function calculateSMA(data, period = 20) {
    const result = [];
    for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
            result.push({ time: data[i].time, value: null });
            continue;
        }
        let sum = 0;
        for (let j = 0; j < period; j++) {
            sum += data[i - j].close;
        }
        result.push({ time: data[i].time, value: sum / period });
    }
    return result.filter(r => r.value !== null);
}

export function calculateEMA(data, period = 50) {
    const result = [];
    if (data.length < period) return result;

    const k = 2 / (period + 1);

    // Seed EMA with the SMA of the first `period` bars
    let ema = 0;
    for (let i = 0; i < period; i++) {
        ema += data[i].close;
    }
    ema /= period;
    result.push({ time: data[period - 1].time, value: ema });

    // Apply EMA from bar `period` onward
    for (let i = period; i < data.length; i++) {
        ema = (data[i].close - ema) * k + ema;
        result.push({ time: data[i].time, value: ema });
    }
    return result;
}

export function calculateRSI(data, period = 14) {
    const result = [];
    if (data.length < period + 1) return result;

    // Accumulate simple average gains/losses over the first `period` changes
    let avgGain = 0;
    let avgLoss = 0;
    for (let i = 1; i <= period; i++) {
        const change = data[i].close - data[i - 1].close;
        if (change > 0) avgGain += change;
        else avgLoss += Math.abs(change);
    }
    avgGain /= period;
    avgLoss /= period;

    // Emit RSI for the first complete period
    let rs = avgGain / (avgLoss === 0 ? 1e-10 : avgLoss);
    result.push({ time: data[period].time, value: 100 - (100 / (1 + rs)) });

    // Apply Wilder's smoothing for subsequent bars
    for (let i = period + 1; i < data.length; i++) {
        const change = data[i].close - data[i - 1].close;
        const gain = change > 0 ? change : 0;
        const loss = change < 0 ? Math.abs(change) : 0;

        avgGain = (avgGain * (period - 1) + gain) / period;
        avgLoss = (avgLoss * (period - 1) + loss) / period;

        rs = avgGain / (avgLoss === 0 ? 1e-10 : avgLoss);
        result.push({ time: data[i].time, value: 100 - (100 / (1 + rs)) });
    }
    return result;
}

export function calculateMACD(data, shortPeriod = 12, longPeriod = 26, signalPeriod = 9) {
    const emaShort = calculateEMA(data, shortPeriod);
    const emaLong = calculateEMA(data, longPeriod);

    // Map long EMA by time
    const emaLongMap = new Map(emaLong.map(item => [item.time, item.value]));

    const macdLineData = [];
    for (const short of emaShort) {
        if (emaLongMap.has(short.time)) {
            macdLineData.push({
                time: short.time,
                close: short.value - emaLongMap.get(short.time) // use 'close' field so we can pass to calculateEMA later
            });
        }
    }

    const signalLineData = calculateEMA(macdLineData, signalPeriod);
    const signalMap = new Map(signalLineData.map(item => [item.time, item.value]));

    const histogram = [];
    const macdLine = [];
    const signalLine = [];

    for (const macd of macdLineData) {
        macdLine.push({ time: macd.time, value: macd.close });
        if (signalMap.has(macd.time)) {
            const sig = signalMap.get(macd.time);
            signalLine.push({ time: macd.time, value: sig });
            histogram.push({
                time: macd.time,
                value: macd.close - sig,
                color: (macd.close - sig) >= 0 ? '#26a69a' : '#ef5350'
            });
        }
    }

    return { macdLine, signalLine, histogram };
}

export function calculateBollingerBands(data, period = 20, stdDevs = 2) {
    const result = { upper: [], middle: [], lower: [] };

    for (let i = period - 1; i < data.length; i++) {
        const slice = data.slice(i - period + 1, i + 1);
        const mean = slice.reduce((acc, val) => acc + val.close, 0) / period;

        const variance = slice.reduce((acc, val) => acc + Math.pow(val.close - mean, 2), 0) / period;
        const stdDev = Math.sqrt(variance);

        const time = data[i].time;
        result.middle.push({ time, value: mean });
        result.upper.push({ time, value: mean + (stdDev * stdDevs) });
        result.lower.push({ time, value: mean - (stdDev * stdDevs) });
    }

    return result;
}

export function calculateVWAP(data) {
    const result = [];
    let cumPV = 0;
    let cumV = 0;
    let lastDate = null;

    for (const bar of data) {
        // Reset at each calendar day boundary
        const barDate = new Date(bar.time * 1000).toDateString();
        if (barDate !== lastDate) {
            cumPV = 0;
            cumV = 0;
            lastDate = barDate;
        }

        const typicalPrice = (bar.high + bar.low + bar.close) / 3;
        const volume = bar.volume || 0;
        cumPV += typicalPrice * volume;
        cumV += volume;

        const vwapValue = cumV > 0 ? cumPV / cumV : bar.close;
        result.push({ time: bar.time, value: vwapValue });
    }

    return result;
}
