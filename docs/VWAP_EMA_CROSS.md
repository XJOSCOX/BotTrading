# VWAP EMA Cross

## Scope and Safety

This is an additive strategy, not a replacement for CRT, Reversal, ORB, VWAP
Reclaim or EMA Pullback. Those definitions remain on completed 15-minute candles.
No account is activated by installation or parameter saving. No copier settings
are changed. Monitoring, simulated paper fills, broker Practice and Leader results
are different populations, never added into a common P&L total.

Default `VwapEmaConfig`: monitor on, broker Practice off, forward-paper off,
CONFIRMED mode, three-minute candles, EMA9 Close, VWAP OHLC4, futures-session
17:00 America/Chicago anchor, 45-bar warmup, 90-second entry window, maximum
10-second trade age, buffered stop, RR 2, adaptive management on five-minute bars.
All optional directional/session/volume/volatility/distance filters default off.
Risk controls outside the strategy remain mandatory.

Leader execution is **prohibited**, not merely unchecked in the UI. Registry
eligibility is enforced when selecting, claiming, building and submitting orders.
Practice requires the new strategy permission, an explicit account arming action,
selection in the account strategy list and all existing preflight checks.
Enabling this strategy cannot enable a paused profile.

## Calculation and TradingView Interpretation

Three-minute UTC buckets require exactly three distinct consecutive minute bars.
OHLC uses first open, maximum high, minimum low and final close; volume is summed.
Incomplete buckets, missing minutes, duplicate inputs and invalid volume are rejected.
Quote/session cumulative volume is never used as per-trade volume.

`OHLC4 = (open + high + low + close) / 4`

`VWAP = cumsum(OHLC4 * traded_volume) / cumsum(traded_volume)` within each session.

`EMA[t] = alpha * Close[t] + (1-alpha) * EMA[t-1]`, `alpha = 2/(length+1)`.
EMA is seeded with the first observed price (`ewm(adjust=False)`), withheld until
the configured length, and additionally guarded by the 45-bar warmup. It carries
scheduled closures but restarts after missing open-market signal buckets. It does
not reset at each VWAP anchor. ATR uses a simple rolling mean of true range; it
is not claimed to match TradingView's Wilder-smoothed ATR.

TradingView documents configurable VWAP source and anchor; its usual default
source is HLC3, not this strategy's OHLC4. For a meaningful comparison select the
same actual contract, three-minute interval, session display, OHLC4 VWAP and EMA9
Close. Historical starting point, EMA seed/history length, trade versus quote
bars, exchange corrections and provider volume can cause differences. Exact pixel
or indicator parity with a particular TradingView feed is not verified here.

Session anchors use IANA wall-clock dates, not a fixed UTC offset. Futures default
is 17:00 Chicago; RTH VWAP is 08:30-15:00 in the configured timezone on weekdays;
custom anchors use the supplied HH:MM/timezone. EMA still uses the supplied
all-hours price history with an RTH VWAP anchor, so compare to an all-hours EMA,
not an EMA computed only from displayed RTH candles. Custom anchors must align
with UTC buckets in standard and daylight time. Ambiguous/nonexistent custom
DST times fail closed. Futures sessions can span 23 or 25 hours around DST.

VWAP never silently starts at a truncated file boundary. Every expected open
minute from the anchor must exist. No price/volume is forward-filled. Zero-volume
bars add zero weight; zero cumulative volume or a zero-volume signal candle blocks
entry. Standard CT daily/weekend closures are encoded. An optional reviewed CME
calendar can only restrict execution windows; it is required for this strategy's
broker Practice entries. This is not an automatic exchange-status service.
Unexpected missing intervals suppress entries and need manual review. See
[Phase 2 validation](PHASE2_VALIDATION.md) for calendar coverage and setup.

## Entry Modes

- **CONFIRMED**: prior EMA <= prior VWAP and current EMA > current VWAP gives LONG;
  inverse inequalities give SHORT. Both bars must be in the same session. Only a
  completed candle confirms, never a forming candle or future price.
- **REALTIME**: the forming bar uses actual minute/trade snapshots through the
  observed sequence. Consecutive eligible observations must cross zero. Detection
  time/sequence and provisional status are stored. Reconnects, old sequences and
  session changes establish a baseline instead of manufacturing a cross.
- **ANTICIPATORY**: experimental same-side convergence, shrinking distance, EMA
  slope and price momentum, maximum tick distance and consecutive observations.
  Signals retain `ANTICIPATED_LONG/SHORT`. Runtime explicitly maps direction to
  LONG/SHORT for the existing lifecycle, without changing the stored classification.
  It is not a confirmed crossover and can disappear/repaint.

At most one directional event per strategy, symbol, actual contract, session,
timeframe, mode and candle is consumed. Event IDs do not depend on the display
name or detection poll. Repeated reads and restarts cannot replay the same event.
Changing a filter or entry mode does not create a second order from a consumed
crossover. A separate canonical consumption key excludes mode and settings;
per-mode immutable event IDs remain available for research. Configuration changes
retain cooldown. Revised finalized history rebaselines provisional detection.
Optional cooldown, minimum separation (ticks/ATR), EMA/VWAP slope, trailing
historical-volume baseline, ATR bounds, CT sessions/custom windows, and maximum
price drift are independently configurable hypotheses, not proven improvements.

Broker entry revalidates the saved indicator event and current conditions at the
current trade price, including intervening stop breaches and a reached reference
target. Reversed provisional crosses and changed anticipatory conditions cancel.
The immutable signal entry is a reference, not a promised broker fill. Actual
broker fills remain authoritative. No automatic reversal is added.

## Stops and Management

Initial stop choices are ATR multiple, recent signal-bar swing, fixed ticks, or
the existing buffered management-candle swing/ATR policy. RR is configurable,
including 1, 1.5, 2 and 3. Stops and targets round outward on the instrument tick
grid and RR is recalculated after rounding/buffering. Long requires
`0 < stop < entry < target`; short requires `0 < target < entry < stop`.

Management choices: fixed stop/target, tick trailing after a configurable R,
break-even after R with a fixed target, or the existing adaptive structure exit.
Adaptive/trailing targets are references, not forced take-profit exits. Levels
and complete settings are frozen per signal/position. Stops can tighten, never
automatically widen after entry. Broker-level linked protective stops remain
required. Software trail updates are **not** broker-stop amendments; API/process
outages can prevent software exits and broker stop fills can slip.

The $500 account loss lock, manual pause, arming, per-symbol 1-4 contracts,
account-wide exposure, additional-symbol sizing, no-hedging, close cooldown,
broker reconciliation, volatility guard, overnight trend/volume/spread checks,
14:50 entry cutoff and 15:05 flatten requests are retained. Unknown submissions
and rejected orders are not blindly retried. Pausing entries keeps exits running.

## Using the Workspace

1. Open **Bot > VWAP EMA Cross > Parameters**. Set the desired mode, symbols,
   anchor, filters and management. Save. This writes only the strategy parameter
   row, not account settings or active trade state.
2. For monitoring, leave Monitor enabled. Start the ordinary feed/monitor worker
   explicitly with the existing launcher. Check actual waiting reasons and trade
   freshness in Signal & chart. No chart is required to keep monitoring running.
3. Complete contract-specific historical coverage is required. Existing legacy
   unlabelled chart bars are not silently attributed to the current contract.
   Use **Load contract session history** here (or open Market) for explicit read-only
   API backfill with contract provenance. This is disabled without credentials.
   History is not automatically fetched on strategy startup. Without backfill, the monitor waits
   until the session has been captured. An API history failure never invents bars.
4. For optional simulated forward testing, enable forward-paper and configure its
   quantity, explicit per-side commission and whole-tick slippage. Zero fees require
   an acknowledged zero-cost sensitivity scenario. It waits for a subsequent actual
   micro trade; it does not submit broker orders. Disabled entries still manage
   existing simulated positions with their frozen configuration. Contract rollover
   with an open paper position stops new paper activity for review.
5. For broker **Practice**, explicitly enable the strategy's Practice permission,
   supply a fresh reviewed calendar as documented in Phase 2, select VWAP EMA Cross
   in Practice execution controls, verify the allowlisted
   isolated account/OCO conditions and arm it yourself. All normal gates still apply.
   MYM needs its existing explicit activation. Never enable a copier accidentally.
6. **Leader cannot run this strategy.** Any future promotion requires a separate
   reviewed code change and verified evidence, not a UI toggle in this feature.

The strategy chart reuses the existing persistent-zoom candle component. EMA and
VWAP share the calculation engine; entry/stop/target levels use the saved signal.
Historical confirmed-cross markers identify mathematical crosses, **not fills**.
Amber intrabar/anticipated markers come only from persisted actual observations,
never reconstructed from historical candle extremes. The main alert includes mode
and anticipated classification. Notifications are in-app only.

## Historical Research

Use **Backtest** with actual minute OHLCV CSV or saved contract-specific history.
CSV timestamps must include timezone offsets; fields are `time,open,high,low,close,volume`.
Choose the actual contract ID, instrument, CT date range, 1-4 contracts, starting
balance, commission per contract/side and adverse slippage per fill. Parameters
control timeframe, mode, filters, stops and RR for VWAP EMA Cross. Existing strategy
adapters preserve their 15-minute signal definitions and buffered stop rules; the
new strategy's filters/risk options do not redefine those adapters.

The date selector retains up to 72 hours of supplied earlier history for warmup;
entries before the selected start are excluded. If that history does not cover
the session anchor or indicator warmup, entries wait instead of constructing a
partial session VWAP. Reported test dates are bounded by actual available data.

Single-contract datasets only; mixed or mismatched contracts and unsupported
rollover policies are rejected. Run separate actual contracts around rollovers.
Contract specifications used:

| Instrument | Minimum Tick | Dollars / Point | Dollars / Tick |
|---|---:|---:|---:|
| NQ | 0.25 | 20 | 5 |
| MNQ | 0.25 | 2 | 0.50 |
| ES | 0.25 | 50 | 12.50 |
| MES | 0.25 | 5 | 1.25 |
| YM | 1 | 5 | 5 |
| MYM | 1 | 0.50 | 0.50 |

Confirmed detection sees only prior completed bars; entries use the next observed
minute open plus adverse slippage, not a retrospectively available signal close.
Stop gaps use the worse open. A stop and target touched in the same minute use
stop first and mark ambiguity. Structure decisions use completed bars and fill
at the next open. Trail changes apply only after the observed bar closes. Missing
intervals force a next-observed-open simulated exit marked ambiguous. Unclosed
end positions are reported separately, not counted as realized trades.

REALTIME/ANTICIPATORY additionally require actual ordered observations with
`time,sequence,price,volume`; optional `contract_id` must match. First observation
after a gap establishes a baseline. Detection cannot fill on its own sequence:
only a later observed trade can fill. A gap through protection after submission
records that fill and an immediate protective exit instead of a favorable
retrospective cancellation. OHLC files alone are explicitly unsupported for
intrabar modes. Replay assumes a complete declared tick observation window;
completeness, bid/ask depth, matching-engine queues and broker latency cannot be
inferred from these files. This is not an account-level execution simulator.

Chronological walk-forward uses expanding training prefixes and later test windows
with historical warmup, never training entries counted as test trades. It does
not optimize parameters by maximum P&L. Walk-forward UI currently supports
completed-minute CONFIRMED runs only. Raw versus filtered runs retain separate
IDs. Other risk/RR/mode alternatives can be saved as independent runs.

Statistics include sample size, wins/losses, gross and net P&L, net profit factor,
expectancy, average/largest wins/losses, average realized R, drawdown, consecutive
losses, holding/exposure, commission and estimated slippage, with session,
instrument, mode and monthly breakdowns. No-loss profit factor is undefined (`--`),
not an artificial large number. Drawdown includes available marked equity in a
run; the comparison's closed-trade statistics cannot reconstruct unrecorded
intratrade drawdown. No commission is assumed: enter a per-contract/side amount,
or explicitly select a zero-cost sensitivity scenario. Positive fees are still
charged when that switch is selected. Research initial-risk and effective-RR limits
do not change account settings. Invalid next-tick fills are recorded with immediate
protective exits, not retrospectively cancelled. Closed-trade net, open entry fees,
realized balance and marked equity are separate; monthly closed-trade returns use
Chicago exit dates. Old implicit zero-fee runs are labeled unverified, not recalculated.

Saved comparisons distinguish historical, forward-paper, broker Practice and
Leader. Historical rows retain run/data hashes/date/size/cost context; paper rows
retain config/contract/size/cost context; broker rows retain account/contract/size
and use only matched fills and reported costs. Filters include symbol, CT dates,
session, strategy and timeframe. No simulated total is added to dashboard broker
P&L. Different sample windows/fees/sizing are visible, not claimed comparable.

No actual historical dataset was bundled for this implementation. Deterministic
synthetic fixtures test arithmetic and causality only; they are not profitability
evidence. False crosses, intrabar repainting, leverage, slippage and correlated
index exposure remain risks. Validate on suitable actual history and forward
Practice data before considering any change to Leader eligibility.

## Architecture Audit and Persistence

The existing pipeline remains: SignalR -> batched `live_ticks` -> saved minute
history -> background `bot_monitor` -> lifecycle/alerts -> account-specific
Practice/Leader worker -> fresh preflight/reconciliation -> claimed job -> broker
submission -> actual fills/exit reconciliation. Streamlit reads state; page
navigation does not own the worker lifetime.

The registry now declares canonical identity, display name, timeframe, indicators,
lookback, supported modes/symbols, cooldown, risk policy, required data, runtime
adapter and execution eligibility. Existing names and setup IDs remain readable.
Indicator/risk functions have no database, network or broker dependencies. The
runtime adapter handles storage/lifecycle; research has no order-placement path.

All schema additions use `CREATE TABLE IF NOT EXISTS`; existing records are not
deleted, renamed or rewritten:

- `strategy_parameters`: validated JSON per canonical strategy ID.
- `strategy_trade_cursor`, `strategy_trade_minutes`: contract-scoped incremental
  actual-trade aggregation with atomic cursors; quotes do not contribute volume.
- `strategy_historical_minutes`: explicit contract-scoped complete API bars.
  A complete historical bar replaces overlapping partial capture, never sums it.
  Nullable `retrieved_at` records when backfill became known; older provenance is
  unknown, not invented. Whole API responses are validated before replacement.
- `strategy_feed_windows`: collector connection coverage. Partial startup minutes,
  restart gaps and detected writer losses cannot establish finalized live minutes.
  Connection coverage is not proof of provider exactly-once delivery.
- `strategy_observations`: restart-safe sequence, gap and convergence state.
- `strategy_signal_events`: immutable unique event snapshots and timestamps.
- `strategy_event_consumption`: durable event-to-alert linkage, including cleared
  watch alerts. Active lifecycle state still uses existing alert tables.
- `strategy_research_runs`: saved historical results/configuration/provenance.
- `strategy_paper_states`, `strategy_paper_trades`: optional simulated micro fills,
  cursors, consumed events and frozen management. No broker jobs are created.

Writes use existing SQLite transactions. Observation/paper updates use optimistic
state comparison under an immediate transaction. Tick ingestion is incremental,
not a write per UI-rendered price. New broker jobs add canonical ID, timeframe,
mode, event ID, settings snapshot and profile; existing account/order/fill/cost
records remain authoritative. Current waiting decisions live in monitor status
and existing deduplicated audit events. Missing historical audit fields are not
fabricated for old trades. Databases, credentials and local account configuration
remain ignored by Git and are not replaced during deployment.

## Verification

```powershell
python -m unittest discover
python -m tests.test_vwap_ema_browser
```

The first command runs deterministic indicator/session/entry/risk/persistence/
research/UI tests and existing execution regressions with temporary databases and
mocked broker interfaces. The opt-in browser check needs a disconnected local
preview at `http://127.0.0.1:8503` (override `GOXTRADE_PREVIEW_URL`), Edge and
Playwright. It checks desktop/mobile tabs, chart pixels, markers, overlays, levels
and retained zoom; it does not press trading controls. Real broker integration,
provider parity, production-volume performance and live fill quality remain
unverified in an offline checkout. Do not run the separate broker smoke-test
script as part of this validation.

## Primary References

- [TradingView VWAP and source/anchor settings](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/)
- [TradingView EMA](https://www.tradingview.com/support/solutions/43000592270-exponential-moving-average/)
- [CME Micro E-mini contract specifications](https://www.cmegroup.com/articles/faqs/frequently-asked-questions-micro-e-mini-equity-index-futures.html)
- [CME E-mini FAQ](https://www.cmegroup.com/trading/equity-index/eminifaq.html)
- [CME equity futures overview](https://www.cmegroup.com/content/dam/cmegroup/education/modules/files/EQ240_EQ_for_AIT.pdf)
