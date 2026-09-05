import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resultsToCsv } from './csv.ts';

test('resultsToCsv: header row present', () => {
    const csv = resultsToCsv([]);
    assert.equal(csv, 'Symbol,ชื่อบริษัท,ราคา,เปลี่ยนแปลง,RSI,MACD,Volume,Signal');
});

test('resultsToCsv: one row, no special chars', () => {
    const csv = resultsToCsv([
        { sym: 'PTT', name: 'PTT PCL', price: 38.5, chg: 0.5, rsi: 55.2, macd: 'Buy', vol: '2.1M', signal: 'Buy' },
    ]);
    const lines = csv.split('\r\n');
    assert.equal(lines.length, 2);
    assert.equal(lines[1], 'PTT,PTT PCL,38.5,0.5,55.2,Buy,2.1M,Buy');
});

test('resultsToCsv: escapes comma in company name', () => {
    const csv = resultsToCsv([
        { sym: 'AAPL', name: 'Apple, Inc.', price: 150, chg: -1, rsi: 40, macd: 'Sell', vol: '10M', signal: 'Sell' },
    ]);
    const lines = csv.split('\r\n');
    assert.equal(lines[1], 'AAPL,"Apple, Inc.",150,-1,40,Sell,10M,Sell');
});

test('resultsToCsv: escapes quote in company name', () => {
    const csv = resultsToCsv([
        { sym: 'X', name: 'The "Best" Co', price: 1, chg: 0, rsi: 50, macd: 'Any', vol: '1', signal: 'Neutral' },
    ]);
    const lines = csv.split('\r\n');
    assert.equal(lines[1], 'X,"The ""Best"" Co",1,0,50,Any,1,Neutral');
});

test('resultsToCsv: neutralizes a company name starting with "=" (formula injection)', () => {
    const csv = resultsToCsv([
        { sym: 'EVIL', name: '=1+1', price: 1, chg: 0, rsi: 50, macd: 'Any', vol: '1', signal: 'Neutral' },
    ]);
    const lines = csv.split('\r\n');
    assert.equal(lines[1], "EVIL,'=1+1,1,0,50,Any,1,Neutral");
});

test('resultsToCsv: multiple rows', () => {
    const csv = resultsToCsv([
        { sym: 'A', name: 'A Co', price: 1, chg: 1, rsi: 1, macd: 'Buy', vol: '1', signal: 'Buy' },
        { sym: 'B', name: 'B Co', price: 2, chg: 2, rsi: 2, macd: 'Sell', vol: '2', signal: 'Sell' },
    ]);
    assert.equal(csv.split('\r\n').length, 3);
});
