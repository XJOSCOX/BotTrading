# Practice Pipeline Latency Audit - October 27, 2026

## Scope

No forced trades, broker test orders, strategy/filter changes, risk changes,
account changes or loss-baseline resets. Leader remains disabled. Runtime
queries were read-only; performance fixtures used temporary databases. All
clock times below are America/Chicago unless explicitly UTC.

## Runtime evidence

Reviewed tick event/receipt timestamps in the bounded query window
22:58:32-23:13:32. The query was bounded to the latest 250,000 raw records;
per-symbol sample counts are retained below, not a claim of exchange completeness.

| Symbol | Recorded observations | Event-to-receipt median | p95 |
| --- | ---: | ---: | ---: |
| MNQ | 15,809 | 1.530s | 1.763s |
| MES | 5,420 | 1.531s | 1.777s |
| NQ | 7,690 | 1.514s | 1.747s |
| ES | 5,180 | 1.526s | 1.772s |
| YM | 1,177 | 1.549s | 1.840s |
| MYM | 2,219 | 1.545s | 1.816s |

This interval mixes provider/application clock offset, transport, upstream
processing and callback handling. It is not a measured pure network delay.
The persisted received_at is recorded when TickBuffer.add enqueues the event;
there is no separate historical transaction-commit timestamp.

For genuine ES Box alert #81 on October 27:

- Completed setup boundary: 23:00:00.
- Alert observed: 23:00:06.041 (6.041s after boundary, not receipt-to-alert).
- First manager selection: 23:00:09.033 (2.992s after alert).
- Executor overnight-trend rejection: 23:00:13.451 (4.418s after selection).
- No order intent or HTTP transmission followed; cannot measure order latency
  for this alert. Overnight trend rejection is not a processing optimization target.

Earlier genuine automated Practice job #10 provides a separate, older example:
October 26 intent at 20:45:05.301, Submitted journal at 20:45:06.812 (1.511s),
first observed fill at 20:45:10.446 (5.145s after intent). These intervals include
preflight/HTTP and broker execution/reconciliation polling respectively; they
do not isolate HTTP round-trip or exact exchange fill latency, and describe an
older in-memory worker build rather than the new optimization.

## Confirmed computation bottleneck

`goxtrade/strategies/signal_candles.py:signal_candles` constructed a Python loop,
date range and pandas Series for every bucket, including every individual
minute when interval=1. Confirmation repeats interval=1 and interval=5 over
the source history; multiple strategies and preflight revalidation amplify it.

Seven-run medians on the same 2,880 genuine NQ historical minutes:

| Operation | Before | After |
| --- | ---: | ---: |
| Aggregate 1m | 519.36ms | 3.49ms |
| Aggregate 5m | 102.91ms | 3.48ms |
| Aggregate 15m | 36.03ms | 3.53ms |
| Pure confirmation of archived ES CRT #80 | 624.58ms | 9.58ms |

The archived confirmation uses 23:01:05 and the same genuine ES history/price
for both implementations; both returned the identical waiting reason and
history-completeness result. These are controlled CPU benchmarks, not actual
market-to-order latency or a guaranteed end-to-end speedup.

The fix uses grouped aggregation, retaining exact completeness, as-of-time,
duplicate and time-cutoff filtering. A group must still contain the exact
number of unique aligned minutes and expected endpoints. First/last rows are
positional rather than pandas first/last, so missing opening/closing values
are not silently skipped. Volume still requires all source-minute values.
Nothing changes expiration, momentum, breakout, stop or risk conditions.

## Follow-up history bottleneck

After the first optimization was deployed, four observed CRT status-update
intervals were 8.926, 8.547, 8.261 and 7.754 seconds. Those are complete monitor
refresh intervals, not computation-only or order latency. Therefore the pure
confirmation improvement was not presented as a complete pipeline fix.

An isolated monitor profile using copied genuine runtime rows attributed 7.648s
of a 9.648s profiled pass to six `load_strategy_minutes` calls. The hot loop
rounded each connection-window start with pandas Timestamp.ceil for every
minute/window comparison. The window starts are constant within a load.

The follow-up fix precomputes the same rounded starts and open-window end once
per connection window. A regression first reproduced six redundant ceil calls
for six source minutes, then passed with exactly one call and unchanged partial
first/last-minute completeness flags.

Five-run medians loading the same 3,142 genuine NQ rows from the same isolated
database at the same frozen clock, refresh=False: **912.60ms before, 173.04ms
after**. Full DataFrames, availability metadata and attrs compare equal. The
subsequent isolated monitor profile was approximately 3.2s; its captured snapshot
and profiling overhead differ from live execution, so it is not an exact live
before/after latency claim. Live monitoring is rechecked after flat-only rollout.

## Other stages

- Read-only last-50,000 priced-tick SQL medians: NQ 163.68ms, ES 150.83ms,
  YM 293.54ms, five local runs each. DataFrame parsing and complete monitor
  cycle costs are not included. No schema/index or history-retention change.
- Existing local thread-wakeup fixture: p50 0.005ms, p95 0.018ms, max 0.049ms;
  this is thread notification only, not worker scheduling under live load.
- Existing temporary-DB 10,000-event burst: all events retained in order,
  zero overflow; 0.3423s total, p95 enqueue-to-commit 323.43ms. Writer starts
  after the burst is queued, so this is not ordinary live commit latency.
- The writer's 50ms batching interval and executor's minimum two-second active
  cycle spacing remain unchanged. The latter protects the shared REST budget
  while retaining full account/positions/orders reconciliation on each cycle.
- Quiet-market trade gaps and required completed-candle waits are distinct
  from computation delays. Bid/ask traffic does not renew a traded-price check.

## Verification and limits

Regression coverage compares the old scalar acceptance algorithm against the
optimized function across intervals 1/3/5/10/15/30/60, gaps, duplicates,
misaligned timestamps, explicit incomplete bars, future/invalid availability,
missing OHLC/volume, empty input and incomplete buckets. Genuine-data outputs
and the archived confirmation result are also equal.

Full verification: 719 isolated tests passed in 100.859s with zero failures or
errors, plus the separate production-path assertion (720 total). Provider HTTP
was blocked in the isolated suite; fixtures did not target the live accounts.

After the coverage-boundary fix, the final complete run passed 720 isolated
tests in 102.902s with zero failures/errors. Including the separate unchanged
production-path assertion, verification totals 721 tests.

No complete historical receipt-to-commit-to-evaluation-to-HTTP-to-fill trace
exists. No such end-to-end latency claim is made. React is outside this worker
execution path. Deployment requires the approved fresh broker-flat checks;
no worker holding a position is to be restarted.
