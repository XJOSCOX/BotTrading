# Evening Practice Entry Audit - 2026-10-27

## Evidence

Read-only local SQLite review of the screenshot alerts: ES Previous Day Box
Reversal #73 and CRT #76 ES / #77 NQ. Times below are America/Chicago, October 27.
Their entry windows are 20:00-20:01:30 and 21:30-21:40 respectively. No test order
was transmitted. Repeated manager decisions are not distinct signals.

| Alert | Confirmation and manager | Executor / outcome |
| --- | --- | --- |
| #73 ES Box SHORT | Confirmed and selected 13 times, 20:00:11.246-20:00:55.608. Planned stop exposure authorized for two contracts. Drift cancellation at 20:01:01.388; expired 20:01:30.534. | Initial conflict veto at 20:00:12.848, repeated with intermittent stale monitor/feed checks. No Practice job or ProjectX submission. |
| #76 ES CRT LONG | Initial micro-price/underlying freshness blocks; then opposing 5m momentum, followed by excessive entry drift at 21:30:26.940. Target reached cancellation at 21:33:34.448. | Never selected; no Practice job or submission. |
| #77 NQ CRT LONG | Opposing 5m momentum at 21:30:06.367; excessive drift at 21:30:31.966; intermittent freshness block at 21:39:36.928; expired 21:40:01.131. | Never selected; no Practice job or submission. |

The two CRTs were detected 0.373s and 4.057s after the 15m boundary. These are
boundary-to-detection deltas, not end-to-end broker latency. There were no order
submission/fill timestamps for these three alerts because no order was sent.

## Confirmed defect and fix

`practice_executor.cycle` checked all Active opposite-direction alerts before
contract lookup and again during preflight. Active includes hypothetical exit
tracking, which deliberately outlives entry eligibility. ES CRT LONG #70 was
detected at 19:15:08.217; its entry window ended at 19:25. Its watch remained
Active until 20:02:16.108. At 20:00 it incorrectly vetoed the manager-selected
SHORT #73, despite being approximately 35 minutes past entry expiry.

`entry_window_history` restricts Practice signal-conflict checks to the existing
entry windows, including the history passed to the overnight conflict check at
both preflight stages. It does not change alert history or hypothetical exits.
Leader retains its previous behavior. Live opposing signals, actual positions,
working orders, unresolved jobs, freshness, confirmation, overnight trend/volume,
stops, risk limits, cooldowns and durable duplicate prevention remain checked.
No entry window was extended and no candle rule was relaxed.

Two mocked executor-cycle regressions failed before the fix (initial veto and
preflight veto), then passed. Additional tests cover the recorded #70/#73 times,
exact expiry, still-current opposite signals, unchanged Leader behavior and
both overnight calls. The existing new-conflict preflight test remains passing.

This proves an erroneous block, not that #73 would necessarily have filled:
later contract, overnight, volatility and repeated broker gates were not reached
on the blocked cycles. Those gates must still pass on future genuine signals.

## CRT reconstruction

Rechecked the persisted completed candles and archived real trade prices during
21:30-21:40: 1,466 fresh ES trades and 1,328 fresh NQ trades. For every distinct
in-drift trade price within each completed-minute interval, re-evaluated the
unchanged entry conditions. ES allowed drift was 0.625 points; NQ 4.25 points.
Both had opposing latest completed 5m momentum initially. All in-drift trades
occurred in the first minute while that support failed. No later fresh trade
was inside the original drift allowance. Neither CRT produced a qualifying
entry in this reconstruction. Their later hypothetical profits do not establish
that their entries met the original rules.

Provider-bar versions at the original decision instant are not retained;
historical refresh replaces bars. Reconstruction uses current persisted bars
with closed-candle cutoffs and archived trades, not an assertion of exact past
provider inputs or exchange completeness. It omits current partial-minute
invalidation and durable cancellation, which can only block additional entries;
even this permissive reconstruction found none. Generated local details:
`data/verification/evening-entry-replay.json` (ignored, not broker results).

Classification: **two CRT alerts correctly unconfirmed in available evidence;
one Box alert affected by a reproduced executor defect; zero proven guaranteed
missed fills.** No saved settings, quantities, safeguards, accounts or loss
baselines were changed to produce this result.

## Verification

60 focused tests passed. The complete isolated regression suite passed 717
tests in 133.244s, zero failures/errors; the separate production-path assertion
also passed (718 total). External provider HTTP was blocked in the test runner.
Local ASGI tests used temporary databases, not the running application accounts.
The sandboxed full-suite attempt stalled in the Windows async test client and
was terminated; the final complete run used the same isolation outside that
sandbox. No additional application defect is inferred from that test limitation.
