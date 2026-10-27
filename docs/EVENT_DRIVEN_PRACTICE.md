# Event-Driven Practice Runtime

## Data Flow

1. The websocket callback queues every delivered tick as before. It never calls
   strategy engines, writes SQLite directly or submits broker requests.
2. The existing batch writer commits ticks in original queue order. Only a
   successful commit publishes a process-local generation notification.
3. The strategy monitor wakes on committed data rather than always sleeping two
   seconds after work. After evaluation it also notifies the executor.
4. The Practice executor wakes on committed data and monitor completion, then
   runs the original execution cycle with fresh broker account/position/order
   reads and every existing signal, risk, ownership and preflight check.

Only wakeups are coalesced, never the stored tick stream. Capturing the generation
before work prevents notifications arriving during evaluation from being lost.
One monitor and one executor remain serialized in their respective threads;
notifications do not spawn overlapping evaluations or concurrent orders.

## Bounds And Recovery

The monitor has a half-second minimum start interval and a two-second idle
watchdog. Strategy computation time still adds to reaction latency.

While Practice is enabled or managing a position, broker reconciliation cycles
start no more frequently than once every two seconds. Idle paused accounts retain
their 15-second cadence. A three-second active watchdog still runs when no events
arrive, preserving scheduled flatten, protection review and reconciliation during
feed outages. Transient-error backoff cannot be interrupted by market events.

The two-second floor leaves headroom below the provider's documented shared REST
budget; it is not a provider-wide quota guarantee for other clients or processes.
Existing HTTP 429 recovery remains authoritative. No REST request is submitted
directly by a tick callback. See the official
[ProjectX rate limits](https://gateway.docs.projectx.com/docs/getting-started/rate-limits/).

Failed persistence still records a feed gap and disconnects. A notification
failure after a successful commit logs a warning and relies on the watchdog;
it does not falsely report already committed data as lost.

Leader remains disabled and retains its existing non-event-driven worker path.
The deployed Practice heartbeat exposes `scheduler=event-driven-coalesced-v1`.

## Unchanged Trading Semantics

- Candle intervals, confirmed-candle requirements, entry windows and overnight
  filters do not change. Faster wakeups are not permission to enter mid-candle.
- Saved strategies, instrument selection, contract quantities, safeguards,
  cooldowns, session policy, loss baselines and manual Run/Pause intent remain.
- Broker stops, fresh-price checks, repeated send-boundary checks, atomic claims,
  consumed setup IDs and unknown-outcome/manual-review locks remain mandatory.
- No older signal is reauthorized merely because the process wakes or restarts.

## Verification

`tests.test_event_wakeup` checks burst coalescing, work-in-progress wakeups, idle
watchdogs, minimum cycle spacing, paused cadence and non-interruptible backoff.
Tick-buffer tests verify durable commit before publication, no publication after
failed writes, and fallback after a notification failure. A 10,000-tick fixture
checks preservation of count, price, volume and order. Signal-lifecycle tests
retain a millisecond stop-touch/rebound rather than replacing it with the latest
price. These are isolated tests, not exchange completeness or broker fill claims.

`tests.benchmark_event_wakeup` measures local thread notification overhead;
`tests.benchmark_tick_ingest` measures temporary-database burst ingestion. Neither
includes the provider feed delay, full strategy evaluation or actual broker fills.
Provider delay and clock skew cannot be removed by a local wakeup change.

## Deployed Verification

The 2026-10-27 release passed 685 isolated regression tests with zero failures,
errors or unmocked HTTP attempts, Python compilation, the production frontend
build and the alert-history desktop/mobile browser checks. The 10,000-tick local
fixture retained every event in order. Cross-thread notification measurements
are saved separately from the real provider data and are not broker-speed claims.

Workers were reloaded only after broker-flat verification. The Practice heartbeat
reports the event-driven scheduler and current source fingerprint. Leader remains
disabled. A newer operator-started Practice session and explicit Safeguards
Save/Apply records appeared during development; these were preserved, not replaced
by the older verification snapshot. Loss baselines were not reset. Because the
session changed during rollout, entries remain paused for a fresh explicit Start
in Execution instead of automatically guessing the operator's latest Run intent.
No test market order was forced.
