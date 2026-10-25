# Bot operations

## Background app

Double-click either CMD launcher for the persistent native interface menu at
`http://127.0.0.1:8504`. Interface start/restart does not start trading workers,
alter Run/Pause or depend on Chrome remaining open. Connection provides explicit
worker controls; guarded worker shutdown requires resolved jobs and verified flat
broker accounts. If verification fails, exit monitoring remains on. There is no
automatic Windows startup. See [NATIVE_APP.md](NATIVE_APP.md). Streamlit on 8502
is retained as an explicitly started fallback, not the default interface.

The feed now retries failed contract discovery as well as failed hub connections.
It reloads `.env` on each attempt, so a repaired API key can take effect on the
next retry. An invalid Topstep key still prevents fresh quotes and entries.

## Execution

- Practice and the allowlisted Trading Combine leader use separate, fixed-account worker processes configured locally in `goxtrade/config/execution_target.py`. No follower routing is performed by this app.
- Leader defaults: 3 MNQ / 3 MES, MYM disabled. Enable MYM trading and Save leader settings explicitly opts into MYM with a selected quantity of 1-4. Disabling blocks new MYM entries without stopping exit management. Starting its monitor leaves entries paused; trading requires the explicit Start control and account/copier confirmations.
- Topstep copier configuration must be verified by the user. The app cannot verify copying or guarantee follower exits. Loss locks apply separately to each account, not the combined copier group.
- Orders, fills, controls, broker health and loss-lock state are account-isolated. Enabled execution or unresolved jobs on the other account block activation. Account-view selectors never arm execution.
- Updated monitoring code watches all three indices and seven strategies. Account controls govern new entries, not management of existing positions. VWAP EMA Cross and Previous Day Box have additional explicit Practice permission and are prohibited for Leader execution.
- MYM additionally requires its existing explicit activation flag. Default execution remains MNQ/MES.
- The persistent $500 account-loss lock and maximum four contracts per symbol remain in force.
- Up to three bot-owned micro positions, one per MNQ/MES/MYM. When flat, the first entry uses the selected size (1-4); with exposure open, new entries on other symbols are capped at one contract each. No additions on the same symbol, no automatic size increases, and no automatic reversal. The opposite-direction exposure guard and account-wide cooldown after any confirmed close remain in force.
- Additional entries require every existing position to reconcile to a bot job with matching quantity/direction and a linked protective stop. Unowned exposure, pending/uncertain entries, closing positions, or unrecognized orders block additional entries. Claims are serialized and the rule is checked again immediately before submission. Exit management continues across all bot positions, even when another job is pending review.
- Emergency close first pauses entries. The worker requests a close only for an identified bot-owned position. It does not retry an uncertain close, cancel unrelated orders, or flatten unowned positions. Flat confirmation requires no positions, orders, or unresolved jobs. Manual review may be required.
- Signal quotes and monitor timestamps must be at most 10 seconds old, and signals at most 15 seconds old. These conditions are rechecked after broker preflight. Stale data blocks new entries; broker backup stops remain in place.
- Protection requires a linked stop with matching parent entry, contract, direction, and size. The existing missing-stop emergency exit remains in force.
- Broker reconciliation continues while paused. A worker heartbeat alone is not evidence of flat exposure.
- Temporary transport errors and HTTP 401/408/429/5xx reconnect with a 3-30 second backoff, preserving the Run/Pause selection. Entries require successful reconciliation and all usual checks. Manual pause, loss locks, rejected or uncertain submissions are not automatically cleared. Non-transient errors still pause entries.

## Audit and notifications

Clear watch-only alerts dismisses active signals unless an account has an open, pending, uncertain, or otherwise unresolved order for them. Closed and rejected jobs do not block clearing. Their job records, fills and P&L remain unchanged. Clearing keeps signal history and releases the monitor for the next distinct setup. It does not close trades or replay the cleared setup. Clearing and order claims are serialized in the database to prevent a cleared watch signal racing an entry.

Topstep execution blocks new entries at 14:50 CT and requests bot-owned position closure from 15:05 CT, ahead of the 15:10 deadline. Known pending bot entries are cancelled; uncertain outcomes and unowned exposure require manual review. Broker flat confirmation requires no positions, orders or unresolved jobs. The schedule also applies while manually paused, never automatically unpauses, and permits entries again at 17:00 CT (Sunday reopening after Friday). Software cannot guarantee timely flattening during API outages; monitor broker exposure. Holiday early closes are not currently encoded and require manual scheduling/pausing.

New events persist in `bot_events`, with consecutive duplicate events suppressed per topic. The inbox is in-app only and survives navigation and restarts. No email, SMS, push, webhook, or external recipient is configured.

Trade review combines existing order-state records and new signal/decision events. Signal trail changes are software exit levels, not broker-stop amendments. Fill observation delay measures when the worker observed a fill, not the exchange's exact execution latency. Historical audit details cannot be reconstructed where they were never recorded.

## Additional monitored strategies

New setups use the shared Stop & trailing candles setting (5 minutes by default; 5/10/15 available). Initial stops use the more conservative of strategy invalidation and the last three completed management candles' swing, plus 0.5 ATR(14), with at least one ATR of distance. Fifteen contiguous completed management candles are required; missing buckets block a new setup. Trailing and two-confirmation structure exits use the same frozen timeframe. Price crossing a protective stop is still checked tick-by-tick. Existing signals without a saved timeframe retain their original one-minute management; settings never widen their stops. Wider initial stops increase dollar risk at unchanged quantity. The separate account loss lock is unchanged.

The five established strategies use completed, gap-checked 15-minute candles: CRT range/sweep, Reversal RSI14, ORB confirmation, VWAP retests and EMA20/50/RSI14. The forming candle contributes no confirmation; live quotes remain available for entry validity and exits. Reversal extreme duration is counted in minutes (each completed 15-minute bar represents 15 minutes). Existing active signals retain their saved levels and exit rules. VWAP EMA Cross declares its own signal timeframe, default three minutes, and explicitly classified optional intrabar modes.

The monitor evaluates CRT, Reversal, ORB, VWAP Reclaim and EMA Pullback for NQ, ES and YM. New strategies are not automatically selected for account orders. Enable them separately in Leader settings or Practice execution controls. Existing account selections, micro sizing, exposure checks, cooldowns and the account loss lock still apply.

- ORB: shared opening-range setting of 5, 15 (default), or 30 minutes from 08:30 CT. Requires complete opening-range data, then two consecutive completed 15-minute closes at least one tick beyond the range following a close inside that boundary. Entries are limited to weekdays before 15:00 CT, subject to the existing market/session gate. Range width provides a reference target.
- VWAP Reclaim: 15-minute HLC3 weighted by summed trade volume, anchored at 17:00 CT. Requires complete minute coverage from the anchor and at least 52 completed 15-minute session candles (13 hours). EMA20/50 alignment and EMA50 slope must agree. A completed candle must retest VWAP within max(one tick, 0.15 ATR), close away from it with a directional body, and follow a close on the same side. A preceding cross identifies a reclaim; otherwise this is rejection. Missing session data or invalid volume yields WAIT.
- EMA Pullback: at least 60 consecutive completed 15-minute candles (15 hours). EMA20/50 alignment and EMA50 slope establish direction. One of the previous three candles must touch EMA20 or EMA50 within max(one tick, 0.15 ATR). RSI14 must cross 50 in the trend direction, with the confirmation candle closing beyond the previous high/low and EMA20, and a directional body.

These five strategies use completed candles and a fresh live price; forming candles cannot confirm their entries. Stops start beyond the setup's candle/range invalidation and use the existing ATR buffer and adaptive exit manager. VWAP/EMA reference targets are twice the initial unbuffered risk; reference targets do not force closure. These are deterministic initial rules, not evidence of profitability. The legacy Replay lab supports CRT and Reversal; the separate historical Backtest workspace has adapters for all six strategy definitions.

Method references: [VWAP](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/) and [EMA](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema).

## Replay lab

Replay is a legacy one-minute research comparison, not a simulation of the current 15-minute live strategy rules. Replay reads already-saved complete minute candles. It does not call the broker, mutate live signals, or apply changes to execution settings. Saved comparisons live in `bot_replays`.

- Baseline: existing buffered stop and three-bar/two-break/1.5R management.
- CRT candidate: five-bar/two-break/2R management.
- Reversal candidate: three-bar/one-break/1R management.
- Optional candidate session filtering and oversized one-minute candle/ATR filtering.
- Configurable costs, slippage per side, and micro quantity; five-minute replay cooldown.
- One symbol and strategy per run, not an account-level portfolio simulation.
- Entries expose the next candle open only; subsequent candle ranges are not used for entry decisions. Stop gaps fill at the worse of the open and stop, with configured adverse slippage. Trail updates occur after the bar closes and never loosen the stop.
- Intrabar ordering cannot be recovered from OHLC. Stops use conservative ordering. Open-at-end positions are excluded from closed results. Historical bars and live-tick-derived candles can differ. Missing historical data is not fabricated.

Candidates and filters are research-only. No promotion control is provided. The first saved CRT comparison did not justify replacing the existing runtime exits.

## Verification

`python -m unittest discover`

`python -m tests.test_bot_workspace_browser` tests navigation and the replay flow headlessly; it does not press execution controls.

`python -m tests.test_leader_browser` checks leader sizing, disabled Start and account views without placing orders.
# Overnight Entry Guard

## Multi-Timeframe Entry Confirmation

New entries for the five established strategies require a current 15m setup, a completed 5m candle whose body and
close-to-close movement support the signal, and a new completed 1m candle after
the setup close. The 1m candle must close beyond the prior candle's high/low, in
the directional outer third of its range, with live price still beyond that close.
The entry window expires five minutes after the 15m setup closes. Invalidation
breaches, an already reached reference target, or drift beyond 0.5 of the original
entry-to-invalidation distance cancel eligibility. Cancellations are persisted per
account profile and alert. Missing/stale data waits, never confirms.

Confirmation is rerun before submission; protective bracket distance is recalculated
from the confirmed live reference price to the unchanged strategy stop. Actual
broker fills remain authoritative. Audit records and alert evidence retain the
confirmation. Existing open positions retain their exit management and stops;
this change adds 1m/5m entry timing, not a new 1m exit rule. These explicit rules
require forward evaluation and do not establish improved profitability.

## Reactive Volatility Guard (All Sessions)

Both accounts check market conditions before creating an entry and again before
submission. A latest/forming 1m true range or live index move above 3x the preceding
14-minute mean true range, a completed 15m true range above 2.5x the preceding
14-bar mean, or a micro spread above four ticks blocks entry. Range baselines
have a four-tick floor. Overnight's stricter two-tick spread cap still applies.
Each detected shock saves a per-symbol five-minute hold shared by both profiles;
continued shocks extend it. Normal conditions and a fresh eligible signal are
required afterward; expired signals are never queued for delayed entry.
Fresh two-sided micro quotes, a fresh index quote, current complete minute history
and enough completed 15m history are required. Missing data blocks entries.
Reasons appear in entry decisions. Existing stops, position management, manual
pause, loss locks and session cutoffs remain unchanged. This is a reactive check
at entry time, not continuous news detection or a scheduled economic calendar;
it cannot prevent a release or spike that starts after submission. Thresholds
are starting safeguards, not validated profitability claims.

From 17:00 to 08:30 Chicago time, both execution profiles require one enabled
strategy on the current completed 15-minute candle, a matching
EMA20/50 trend and EMA50 slope, and candle volume at least the median of the
previous 20 candles. Trend confirmation requires 52 completed candles; scheduled
market closures may be bridged, but missing open-market candles still block entry.
Conflicting active enabled strategies remain blocked. A second agreeing strategy
is no longer required (revised after the September 23 overnight block review).
The actual micro contract must have fresh bid/ask timestamps (at most 10 seconds),
valid tick-aligned prices and a spread no wider than two ticks.

Overnight entries are limited to one micro contract and one position at a time,
with a minimum 15-minute post-close cooldown. These checks run again before order
submission. Block reasons are recorded in the existing alert decision history.
Regular-session sizing, strategy stops, exit management, manual pause and account
loss locks remain unchanged. These starting thresholds require forward testing;
they do not establish a higher win rate or guarantee profitability.

## VWAP EMA Cross Workspace

See [VWAP_EMA_CROSS.md](VWAP_EMA_CROSS.md) for its independent indicator-event entry
policy, session coverage, settings, risk modes and research assumptions. Monitoring
starts with CONFIRMED three-minute signals. Practice and forward-paper are disabled
by default; Leader eligibility is denied at settings, claim and submission boundaries.
The account-level $500 lock, exposure, schedule, stale-data, volatility, overnight
trend/spread and reconciliation gates still apply. The legacy 15m/5m/1m trigger is
not silently applied to this separate indicator event; its original crossover must
be revalidated within its saved entry window (90 seconds by default).

Do not confuse its configurable session research filter with execution permissions.
Disabling research filters cannot bypass account safeguards. Opposite crosses do
not reverse positions. Settings changes apply to new setups; active positions keep
their frozen initial levels and management configuration.

## Delayed Monitoring Diagnosis

Phase 2 adds mode-independent VWAP crossover consumption and stricter persisted
order identity checks. Ambiguous new-strategy metadata fails closed; Leader stays
prohibited. Final submission rechecks pause, balance loss lock, conflicts, schedule
and freshness. No account limits or copier configuration were changed. Historical
and simulated-paper fees must now be explicit. See [PHASE2_VALIDATION.md](PHASE2_VALIDATION.md)
for the required reviewed-calendar setup before VWAP broker Practice, data recovery,
tests and remaining limitations. No execution was enabled during validation.

Practice entry confirmation update (October 9, 2026): the entry window is ten
minutes after the 15m setup closes, allowing evaluation of a post-setup 5m close.
Price outside the existing 0.5-setup-risk distance is Waiting, not a permanent
cancellation; it must return inside the same limit and pass all candle and live
price checks before entry. Invalidation, target and expiry cancellations remain.
Previously cancelled alerts are not reset. Leader retains its five-minute window
and durable price-distance cancellations. This is a Practice timing experiment,
not evidence of improved profitability. Expiry and stale-feed block messages are
reported separately.

Fresh feed ticks do not prove that strategy evaluations are current. On October 8,
2026 a monitor cycle took 127 seconds, almost entirely opening/reading SQLite.
The WAL was about 12 GB and checkpointing the original file failed with
SQLITE_IOERR_WRITE despite available disk space. A separate database-plus-WAL
copy checkpointed successfully. Never delete a WAL to clear this condition:
it may contain committed orders, fills, alerts and safety settings.

Pause entries and verify broker positions and orders before stopping workers for
database maintenance. Preserve the database and WAL together while all database
processes are stopped; checkpoint and integrity-check a recovery copy before use.
Restart monitoring with entries paused and verify all strategy/symbol timestamps
and feed freshness before manually resuming. Existing database connections no
longer run core schema creation, and each evaluation refreshes its latest tick
after loading candle history. Stale-data entry guards remain in place.

## Previous Day Box Addition

See [PREVIOUS_DAY_BOX.md](PREVIOUS_DAY_BOX.md) for the new completed-session/15m
reversal strategy. It cannot activate Leader execution. Monitoring defaults on;
paper and Practice require explicit opt-in and never bypass existing safeguards.
Missing prior-session history returns WAIT rather than using an older or mixed
contract box. New monitoring modules require a guarded worker restart; interface
restart alone never interrupts trading workers or authorizes entries.

## Strategy Manager / Shadow and Research Only

Use Strategy Manager in the native sidebar or the legacy Strategies tab. Both
Practice and Leader show the complete strategy catalog and shared interval,
indicator and Box controls; restricted Leader execution choices stay visible but
cannot be selected. Research policy is shared, account entry permissions are not.

Portfolio paper is a separate ledger, off by default. Set explicit costs and
research limits, enable separate paper entries, then explicitly start its worker.
Turning paper entries off cancels pending paper fills while existing paper exits
continue. It does not change broker Run/Pause settings. Do not use paper results as
broker fills or assume its risk policy changed funded-account controls.

Existing broker workers and alert-ID selection remain unchanged. The manager's
broker authorization and broker reservations are prohibited pending a separately
reviewed cutover. See [Strategy Execution Manager](STRATEGY_EXECUTION_MANAGER.md).
