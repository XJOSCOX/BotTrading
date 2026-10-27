# Missed Practice Entry Audit - 2026-10-27

## Scope and evidence

Reviewed main at `5a96c7d`, verified equal to fetched origin/main before edits.
Runtime evidence is the local SQLite database and existing collector logs, not
simulated P&L. No broker order was forced, account reset, or safeguard changed.
Leader remained disabled. All times below are America/Chicago on October 27.

The starting trio is the simultaneous 11:15 CRT alerts: ES #55, NQ #57, YM #58.
To cover the other plausible interpretation of "three CRT alerts," the later ES
#60, YM #61 and NQ #62 were also examined, plus ES #63. Their entry windows span
11:15-14:40; this is a retrospective record review, not continuous observation.
Additional preflight traces #45 and #54 were reviewed separately.

## Signal-to-order call paths

| Stage | Reviewed files/functions | Finding |
| --- | --- | --- |
| Ingestion | `runtime/run_live_market.py` callbacks; `data/tick_buffer.py` write_batch | Raw ticks remain sequenced and committed before event wakeups. Quotes and trades are distinct. |
| Candle history | `data/chart_history.py`; `data/strategy_history.py` refresh_trade_minutes/load_strategy_minutes | Contract-specific trade bars carry coverage/availability metadata. Historical bars replace partial captures, without summing volume twice. Missing minutes are not synthesized. |
| Candle aggregation | `strategies/signal_candles.py` signal_candles | Confirmed metadata-integrity defect described below. UTC bucket alignment and consecutive-minute count checks are otherwise intact. |
| Strategies | `bot/bot_monitor.py` evaluate_strategy_status/monitor_once; `strategies/crt_strategy.py` evaluate_crt | CRT uses completed 15m sweep candles, then separate entry confirmation. A detected setup is not an entry authorization. |
| Lifecycle | `bot/signal_lifecycle.py` advance_signal/track_signal | Active watch tracking can outlive its entry window and suppress another setup in the same symbol/strategy slot. This existing lifecycle policy was not changed. |
| Confirmation | `strategies/entry_confirmation.py` evaluate/check/window_open | Requires completed 5m support, a post-setup completed 1m directional break/strong close, fresh follow-through, intact invalidation and permitted drift. Target reached and expiry remain cancellations. |
| Manager | `execution/practice_automation.py` selection/validate_payload; `execution/strategy_manager.py` eligibility/evaluate; `execution/portfolio_risk.py` authorize_risk | Confirmation, arbitration, account ownership, stop geometry, quantities and risk limits remain mandatory. Repeated decisions are not new signals. |
| Executor | `execution/practice_executor.py` cycle/claim/retryable_preflight | Atomic claim, fresh broker reconciliation, repeat validation, exact-account/session gates and durable pre-HTTP SENDING marker remain in place. |
| ProjectX/reconciliation | `execution/projectx_client.py` post; `execution/practice_history.py`; executor position/stop reconciliation | Actual HTTP acknowledgement is distinct from fill and protection. Unknown outcomes do not retry. The seven CRT alerts have no matching submitted Practice jobs or broker orders. |

## Starting CRT trio

| Alert | Detection after 15m close | Recorded timeline | Classification |
| --- | --- | --- | --- |
| #55 ES SHORT | 11:15:00.531, +0.531s | Waiting for the first 1m close; no directional break/strong-close confirmation; at 11:20 the latest 5m body/momentum opposed the short; expired 11:25. | Correctly blocked in examined evidence. |
| #57 NQ SHORT | 11:15:04.246, +4.246s | First post-setup 1m trigger did not qualify; subsequent 5m momentum failed; price also exceeded 0.5 original setup-risk drift; expired 11:25. | Correctly blocked in examined evidence. |
| #58 YM LONG | 11:15:08.426, +8.426s | 5m support failed, then entry drift failed; invalidation was recorded breached at 11:15:21.150; later expired. | Correctly blocked; invalidated before entry. |

These detection deltas include scheduling, data access and persistence, not just
strategy computation. All three were detected before a new completed post-setup
1m candle could exist. There is no evidence that these detection delays caused an
otherwise authorized entry to expire. None reached manager selection or HTTP.

## Additional CRT alerts

| Alert | Entry window | Recorded blocker |
| --- | --- | --- |
| #60 ES SHORT | 12:30-12:40 | Unrecognized working order at 12:30:10 blocked new entries; after reconciliation cleared, 5m momentum did not support direction. |
| #61 YM SHORT | 12:45-12:55 | Initially opposing 5m momentum, then excessive drift and intermittent freshness failures. Reconstructed trigger patterns at 12:52/12:54 had no observed trade meeting original drift/follow-through/level conditions. |
| #62 NQ LONG | 13:15-13:25 | No qualifying 1m follow-through, then opposing 5m momentum, then expiry. |
| #63 ES SHORT | 14:30-14:40 | Awaiting the first 1m trigger, intermittent excessive drift, then invalidation at 14:31:01.311. |

Count: **7 CRT alerts legitimately blocked in the examined records; 0 proven
incorrectly missed eligible orders.** No qualifying entry was found in the
archived-event reconstruction. This is not a claim of complete exchange delivery.

## Historical reconstruction and limitations

Reconstructed minute OHLCV from archived priced events for the actual December
NQ/ES/YM contracts, preserving event/receipt times and event order. The model uses
closed-candle availability, actual post-detection trade prices, original stops,
the unchanged ten-minute entry windows, drift limits and the existing evaluator.
Every qualifying actual trade in a completed-candle interval was considered;
no periodic sample was used to substitute for a price crossing. No simulated
entry was submitted or included in account profit.

Original provider-bar versions at each decision were not retained: refreshes
replace those rows. Archived quote/trade-derived candles can therefore differ
from the authoritative historical bars available to the original evaluation.
Connection windows do not prove exchange-level exactly-once delivery. These
limitations prevent claiming an exact reproduction of every original input or
proving that no unrecorded transient opportunity ever existed.
Local reconstruction output is in ignored `data/verification/missed-crt-reconstruction.json`.

## Preflight review

For NQ #45, the manager selected one contract at 09:03:03.792, price 29,561.25.
At 09:03:07.645 it no longer confirmed follow-through, price 29,557.25. The job
was aborted before HTTP. The approximately 3.85-second interval is supported by
timestamps; no entry-window expiration occurred during that interval. Removing
this recheck would accept a setup that no longer qualified, so it was retained.

MES #54 was aborted at 10:17:17.060 by a combined signal/freshness preflight check.
The combined message does not preserve which individual boolean failed. Do not
attribute it more precisely than the stored evidence permits. Neither local
preflight abort was a ProjectX rejection. Existing main already includes durable
proven-unsent retries and the confirmation-clock race fix; those were not
reimplemented or used to replay old jobs.

## Confirmed fix in this audit

Affected function: `strategies/signal_candles.py::signal_candles`.

Root cause: minute count and timestamp alignment were checked, but explicit
`complete=False` and a known future `asof_time` were ignored. A past-tense
timestamp alone could therefore turn a partial capture into a confirmed candle,
and the confirmation evaluator could report Confirmed on that incomplete input.

Reproduction before the fix: three focused tests failed, including an actual
call to the confirmation evaluator returning Confirmed for a minute explicitly
marked incomplete. This is a demonstrated implementation defect, but its role
in the seven historical misses is **not established**: the legacy chart inputs
and original provider-bar versions do not retain sufficient provenance.

Exact fix: exclude explicitly incomplete source rows and source rows with a
known availability timestamp later than evaluation, before candle aggregation.
Missing optional availability metadata remains compatible with legacy history;
an invalid non-null availability timestamp fails closed. No minutes are filled,
no window extended, no entry condition removed, and no original stop changed.

Behavior change: only candles previously accepted despite explicit incomplete
or unavailable-source metadata are now rejected. This prevents false confirmed
setups; it does not manufacture additional trades or guarantee higher frequency.

Regression tests cover incomplete 15m source data, incomplete 1m entry
confirmation, future availability, and optional legacy availability metadata.
Focused verification: 71 tests passed. Full verification: 707 isolated tests
passed with zero failures, errors or unmocked HTTP attempts; the production-path
assertion passed separately (708 checks in total). Detailed local output is in
ignored `data/verification/missed-entry-audit-regression.log`.

The operator-approved market/Practice reload was performed only after direct
broker checks confirmed no positions or working orders, and after the old worker
acknowledged paused entries. The exact Practice settings and Run/Pause selection
were restored. Saved/active safeguards, controls, parameters, manager/profit
policies, loss baselines and Leader-disabled settings compared unchanged across
the reload. No Leader worker was restarted and no real test order was forced.
