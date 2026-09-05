import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getSetStatus, getUsStatus } from './marketStatus.ts';

// All timestamps below are UTC; getSetStatus() converts to Bangkok (UTC+7)
// internally, getUsStatus() converts to simplified ET (UTC-5).
// Monday 2026-09-07 is used as a weekday anchor throughout.

test('getSetStatus: 16:00-16:30 ICT (09:00-09:30 UTC) is still Open — the Dashboard bug this bd fixes', (t) => {
    // 09:15 UTC = 16:15 ICT -> inside the 14:30-16:30 afternoon session
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-07T09:15:00Z').getTime() });
    const status = getSetStatus();
    assert.equal(status.open, true, 'DashboardPage previously used getHours() < 16 which wrongly closed the market at 16:00');
});

test('getSetStatus: 16:30 ICT (09:30 UTC) exactly closes', (t) => {
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-07T09:30:00Z').getTime() });
    assert.equal(getSetStatus().open, false);
});

test('getSetStatus: lunch break 12:30-14:30 ICT is closed (not just "open until 16:00" as old heuristic assumed)', (t) => {
    // 06:00 UTC = 13:00 ICT -> lunch break
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-07T06:00:00Z').getTime() });
    assert.equal(getSetStatus().open, false);
});

test('getSetStatus: morning session 10:00-12:30 ICT is open', (t) => {
    // 03:30 UTC = 10:30 ICT
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-07T03:30:00Z').getTime() });
    assert.equal(getSetStatus().open, true);
});

test('getSetStatus: weekend is closed regardless of time', (t) => {
    // 2026-09-05 is a Saturday; 03:30 UTC = 10:30 ICT (would be open on a weekday)
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-05T03:30:00Z').getTime() });
    assert.equal(getSetStatus().open, false);
});

test('getUsStatus: regular session 09:30-16:00 ET is open', (t) => {
    // 15:00 UTC = 10:00 ET
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-07T15:00:00Z').getTime() });
    assert.equal(getUsStatus().open, true);
});

test('getUsStatus: after-hours 16:00-20:00 ET is closed', (t) => {
    // 22:00 UTC = 17:00 ET
    t.mock.timers.enable({ apis: ['Date'], now: new Date('2026-09-07T22:00:00Z').getTime() });
    assert.equal(getUsStatus().open, false);
});
