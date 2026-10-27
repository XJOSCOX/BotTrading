# Practice Release Audit

Date: 2026-10-26, America/Chicago. Scope: supervised automatic Practice execution,
not profitability certification or a guarantee against future provider failures.

## Approved Configuration

- All seven registered strategies selected for the existing Practice account.
- MNQ only; one contract per new entry. Saved MES/MYM quantities are retained,
  but their Practice entries are disabled for this test.
- Leader remains disabled. No account identity, credentials or copier settings
  are replaced. Stored alerts, orders, fills and loss baselines are preserved.
- The operator explicitly retained the saved USD 1,000 cumulative account loss
  lock after inspection showed it was not USD 500. Planned trade risk remains
  USD 250 and total open stop risk USD 500. No risk ceilings were raised here.
- Normal cooldown remains five minutes; the active overnight floor remains
  15 minutes, with one contract and maximum two-tick spread. Existing volatility,
  freshness, position ownership, calendar and duplicate/unknown-outcome gates stay.
- Paper settings are unchanged. Broker stops are required. No signal or order
  is fabricated to make a strategy appear active.

VWAP EMA Cross: monitor and Practice enabled, Leader disabled, actual MNQ source,
three-minute confirmed candles, EMA9 Close, OHLC4 VWAP anchored 17:00 Chicago,
45-bar warmup, 90-second entry window and ten-second maximum data age. Buffered
stops, ATR settings 14/1.5, fixed-method setting 12 ticks, reward/risk two,
adaptive five-minute management and signal notifications are retained. Optional
strategy separation/slope/volume/volatility/session/distance filters are off.
Global safeguards are not disabled by those optional strategy settings. The
buffered method computes its own structural/volatility stop; 12 ticks is not
substituted as the actual buffered stop or used to bypass missing warmup.

## Confirmed Defects Fixed

| Finding | Repair and evidence |
|---|---|
| Empty explicit strategy selection fell back to saved strategies | Empty now fails authorization; no implicit re-enabling. Regression added. |
| Entry-policy Save silently re-added MES | Instrument choices persist through explicit and older client saves. MNQ/MES controls added to the existing form; MYM retains its opt-in. Both account adapters tested. |
| Monitoring could look broker-authorized while paused | Existing strategy matrix now distinguishes watch-only, selected/paused, missing opt-in, stale worker, session restart and armed state. |
| Diagnostics mixed other-account/research rejections with Practice evidence | An additional column reads only this Practice account's actual execution-manager decisions; unknown reasons are not guessed. |
| Actual micro historical replay was evaluated using a mini source alias | Existing VWAP/Box adapters now retain the dataset's actual instrument identity. A real Box calculation on a micro-contract fixture verifies the route. No strategy condition was relaxed. |
| Portfolio summaries reported zero holding time/slippage because fields were absent | Closed portfolio trades now record elapsed holding seconds and the already-modeled slippage cost. Trading decisions and fills are unchanged. |
| A confirmed closed broker trade could leave its shared watch lifecycle active | Reconciliation closes only proven closed traded alerts, releases the matching lifecycle and preserves consumed crossover IDs. Other-account ownership and unknown jobs block cleanup. Actual exit fills can arrive later without inventing a price. |
| Obsolete one-strategy/smoke aliases remained | Removed the retired HTTP action and smoke-script alias; retained the canonical operator diagnostics, durable history compatibility and necessary regression tests. |
| Static audit failed on pending file deletions | Inventory skips deleted files instead of attempting to parse absent sources. |

## Seven-Strategy Verification

All seven IDs resolve through the existing catalog, monitor adapters, Practice
selection, manager arbitration and common executor. Legacy setup analysis uses
the configured index reference feed; actual orders map to the active MNQ micro
contract, and fills are reconciled from the broker rather than assumed equal to
the reference price. VWAP EMA Cross uses the selected actual MNQ trade history.

| Strategy | Signal / confirmation | Observed legitimate wait or evidence |
|---|---|---|
| CRT | 15-minute sweep/reclaim, existing 5m/1m entry checks | Genuine saved short alert observed; old/expired alerts are not replayed into a new session. |
| RSI Reversal | Completed 15-minute RSI14 | Current warmup available; waiting for the existing RSI reversal condition. |
| ORB | Existing 15-minute opening range and 15-minute confirmation | Cash-hours-only strategy; correctly inactive during overnight observation. |
| VWAP Reclaim | 15-minute session VWAP with EMA20/50 | Needs 52 completed current-session candles; current overnight session had only 18 at inspection. |
| EMA Pullback | 15-minute EMA20/50 and RSI momentum | Needs 60 contiguous completed candles; latest contiguous run had 18 at inspection. Scheduled daily gaps are not fabricated away. |
| VWAP EMA Cross | Finalized three-minute crossover | Warmup available; live indicator snapshot reports no new crossover. Existing crossover IDs remain consumed/deduplicated. |
| Previous Day Box Reversal | Previous complete contract session plus 15-minute confirmation | Live previous-session box is verified; latest confirmation outside its entry window correctly waits. |

Warmup/session waits are not implementation failures. All seven being selected
does not mean all seven must trade overnight or enter on every monitor alert.
Existing adaptive software exits and original broker-stop protection remain in
place; unverified broker partial exits/amendments are not activated by this audit.

## Validation And Evidence

- Full regression: 660 tests pass. Entry/exit reconciliation, rejected/unknown
  outcomes, isolation, risk limits, cooldown, schedule, duplicate prevention,
  protection and the new fixes use disposable state and mocked broker transport.
  The final run additionally blocked requests transport and observed zero
  unmocked HTTP attempts during discovery and test execution.
- Python compilation and dependency consistency checks pass. Production frontend
  build passes; production npm audit reports zero advisories at audit time.
- Real-API/disposable-DB browser checks verify both profiles, strategy all-off,
  MYM, MNQ-only persistence, sizing, reload/reconnect drafts and save failures.
- Desktop/mobile route, chart, zoom, pane sizing and authorization-dialog checks
  pass without production writes or submitted orders.
- Existing static inventory was run across the tracked/unignored source/config/
  documentation tree. Static parsing is not measured branch or security coverage.
- Existing portfolio replay evaluates the seven adapters against real finalized
  ProjectX MNQ OHLCV, with fixed cash and overnight windows. No synthetic source
  is inserted. Historical replay uses finalized provider candles, not live
  capture availability timestamps. Simulated fills are not actual broker fills.
  The final dataset contained 7,008 authentic finalized bars. Each sampled window
  evaluated 100 minutes. Box reached eligible arbitration and one virtual position
  remained open at the overnight window end; other eligible setups were blocked
  from adding the same instrument. No closed simulated trade or actual broker
  order was forced. Cash-window candidates either lacked confirmation or were
  outside their entry windows.
- Private configuration snapshots, real history, hashes, replay outputs and logs
  remain ignored under `data/verification/`; no credentials or account identifiers
  are published in this report.

## Operating Boundaries

The reviewed calendar currently ends **2026-10-27 at 16:00 CT**. Review its official
coverage before expiration; do not bypass that gate to increase trade frequency.
Entries stop at the existing 14:50 CT cutoff, with scheduled flatten at 15:05 CT.
Loss locks, uncertain order outcomes, incomplete candles and missing protection
can still stop new entries and require operator attention. They are not silently
unlocked or reset. The computer must remain awake for software-managed exits;
broker original stops remain independent of the interface.

This is a release for supervised Practice automation. A bounded replay and one
successful broker round trip do not establish every future outage or multi-day
unattended behavior. Diagnostics reports current evidence rather than issuing an
unconditional production certificate. See [Practice Operations](PRACTICE_OPERATIONS.md).

## Deployment Result

After the final tests, both flat account workers were reloaded and their source
fingerprints verified. The operator-approved Practice session was started exactly
once through the existing authenticated API. The actual saved session is armed
with all seven strategies, instruments `[MNQ]`, and one requested MNQ contract.
The worker reports monitoring positions/new signals; passive operational checks
pass. At the release snapshot there were no new-session broker jobs. This is
automatic authorization for future eligible signals, not a statement that an
order has already been filled.

The deployed browser was checked on desktop/mobile: seven armed strategy rows,
MNQ selected, ES/YM watch-only, no page overflow or JavaScript errors. Raw saved/
active Safeguards records and revisions, loss baselines, Leader settings and
Leader controls were compared with pre-work snapshots and preserved. VWAP paper
settings and the other six strategies' algorithms/configuration are unchanged.

## Repository Consolidation

The validated release is retained on `main` only. All other branch tips
were verified as ancestors before cleanup. The older primary checkout contained
38 unrelated modified/untracked paths; it was detached at its existing commit,
and every preserved file was verified byte-for-byte unchanged. Those local edits
are not silently folded into this release. Use the active release worktree's
`start_app.cmd`, not the older detached checkout's legacy launcher.
