# Phase 2 Validation Report

Validation date: October 24, 2026. Branch: `feature/vwap-ema-cross`.
This is a technical validation milestone, not a claim of trading profitability.

## Audited Baseline

Fetched origin before editing and verified a clean worktree. Audited implementation
commits `4b4c437` (backend), `c63b667` (UI), and latest `284bc82` (documentation).
Compared the feature against `main` / redesign baseline `a0d7fbe`. No subsequent
remote implementation changes were present. No merge into main was performed.

The existing pipeline remains SignalR -> TickBuffer -> `live_ticks` ->
contract-specific minute history -> pure indicators/strategy -> persisted
observation/event -> lifecycle/alert -> account-specific eligibility and claim ->
reconciliation/final preflight -> broker submission -> authoritative fill/close
history. Research and forward paper have no broker order-placement path.

No real orders, API authentication, smoke-test trades, or account arming were used
for this audit. Broker tests use mocks and isolated temporary databases. The local
UI preview runs Streamlit only, not the feed or execution workers. Credentials,
account identities, copy settings and existing trading history were not replaced.

## Confirmed Defects and Fixes

| Severity | Confirmed defect | Correction and regression coverage |
|---|---|---|
| High | Ambiguous/stripped indicator identity could fall through legacy compatibility; inconsistent ID/name could hide provenance | Reject indicator markers without canonical identity, mismatched names/timeframes and incomplete frozen envelopes. Claim checks persisted original alert. Leader denial at all execution boundaries. `test_phase2_execution_safety` |
| High | Changing entry mode could replay the same underlying crossover | Separate mode-independent consumption hash; atomic profile entry claims; legacy aliases derived from immutable history; paper/watch consumption retained after restart/clear. Research event IDs remain distinct. Execution/data/research tests |
| High | Failed observation compare-and-swap could leave anticipated direction available for later re-promotion | Clear raw direction/event and prohibit new lifecycle entry on lost CAS. Invalid settings still allow frozen active exits. Empty-history timestamp handling corrected. Data/integration tests |
| High | Partial startup/reconnect live minutes could be treated as finalized | Add connection windows, clamp crash/failed-writer coverage, require complete management minutes; contract history remains authoritative. Data and TickBuffer tests |
| High | Incomplete or invalid API history could replace valid saved bars; retrieval knowledge time was absent | Validate entire response before writing; reject duplicate/bad OHLCV/contract data, retain retrieval timestamp and exclude future-known history. Data tests |
| High | Silent zero commission made research/paper results misleading | Require explicit commission, permit zero only with acknowledged sensitivity switch; positive fees remain charged. Label old implicit-zero runs unverified. Research/UI tests |
| High | Slipped fills could violate geometry/RR/risk without clear classification | Revalidate research fill risk/RR; minute preflight refusals counted; committed next-tick invalid fills recorded with immediate protection and costs. Research tests |
| High | A tightened tick-managed stop could be crossed at the current observation but not handled immediately | Recheck updated protection at that observation; no future-bar exit logic. Research tests |
| High | Pause/loss/conflict changes during broker preflight could escape earlier checks | Recheck balance lock, pause, conflicting signals, claimed identity, schedule/window/freshness before send; retain quantities, exposure and linked stops. Execution safety tests |
| Medium | Settings reset cooldown; history corrections could manufacture intrabar crosses; anticipatory momentum used the wrong observation | Seed cooldown from persisted events, hash finalized context and rebaseline corrections, use prior observation momentum. Data/indicator tests |
| Medium | Distance/ATR filters could silently omit a requested restriction | Enforce both enabled caps; missing required ATR blocks rather than ignores filter. Data/indicator tests |
| Medium | Contract/tick-grid mismatches and rollover could misprice research or pending paper entries | Reject known ProjectX product mismatch, mixed/null contract IDs, off-grid prices and cross-expiry executable contracts; cancel pending old-contract paper entries. Data/execution/research tests |
| Medium | Open fees/marked equity were not explicitly separated from closed results; month grouping used UTC | Separate closed net, realized balance, open fees and marked equity; CT closed-trade monthly returns. Research tests |
| Medium | Paper legacy-consumption migration might not persist without another state change | Compare final state to original persisted state, not migrated working state. Dedicated wrapper migration regression |

Existing CRT, Reversal, ORB, VWAP Reclaim and EMA Pullback entry definitions remain
15-minute. Their original regressions and all six research adapters execute. Flat
synthetic adapter fixtures establish compatibility only, not comparative returns.
No legacy strategy formula, account loss limit or copier setting was changed.

## Indicator and Mode Validation

EMA9 Close uses alpha 0.2, first observed close seed, `adjust=False`, minimum
length and configured 45-bar warmup. Independent Decimal recursion verifies
expected values. Session VWAP uses OHLC4 times actual traded volume; a literal
weighted-sum fixture verifies `6651 / 66`, not a second invocation of the engine.
RTH excludes outside-session weights. Futures 17:00 Chicago sessions, midnight,
DST, zero/invalid volume, incomplete buckets, missing history and no-lookahead
cases are covered. Missing open-market data blocks/rebaselines rather than fills.

CONFIRMED requires completed consecutive buckets and exact prior/current sign
inequalities. REALTIME requires ordered consecutive actual observations and
rebaselines after gaps, reconnects or finalized-history changes. ANTICIPATORY
requires same-side convergence and observation momentum/count; it stays labeled
experimental and provisional. Cancellation is rechecked before entry; disappearance
does not erase the immutable audit event or retroactively undo a simulated fill.
Consumed direction/session/contract/timeframe/candle keys survive mode changes.

TradingView parity is **unverified**: OHLC4 is intentional rather than usual HLC3;
EMA seed/history, provider volume/corrections and displayed sessions must match.
ATR is a simple rolling true-range average, not TradingView Wilder smoothing.

## Data Audit and Recovery

Read-only workspace audit found **0 rows** in each of `live_ticks`,
`strategy_historical_minutes`, `strategy_trade_minutes`, and `historical_minutes`.
No credentials were available for authenticated historical retrieval.

| Requested period/instruments | Genuine results |
|---|---|
| Latest month: NQ/MNQ/ES/MES, optional YM/MYM | Unavailable: no validated historical data |
| Previous three months | Unavailable: no validated historical data |
| Previous six months | Unavailable: no validated historical data |
| Filter/RR/stop variants or chronological optimization | No actual-market conclusions; deterministic engine tests only |

No missing candles, volume, trades or profitability were fabricated. The explicit
**Load contract session history** button performs read-only authenticated retrieval
when configured by the operator; startup does not automatically fetch history.
Wait for full session coverage and fresh event/receipt timestamps. Old unlabelled
chart bars are not assigned to the active contract. Backfill wins over overlapping
partial capture without summing volume. Preserve database/WAL together; do not
clear consumption or alert history as a recovery shortcut.

ProjectX documents no unique market GatewayTrade ID. A local ingestion cursor
prevents re-aggregating the same saved row, and provided research event IDs are
checked for duplicates, but this cannot prove provider exactly-once delivery.
Identical price/time/volume messages may be legitimate trades, so no heuristic
tuple deduplication was introduced. Quote cumulative volume is never trade volume.

## Simulation Methodology

Fees are explicit per contract/side; no current Topstep fee preset is invented.
Adverse whole-tick slippage applies to entry and exit. Confirmed OHLC research
uses the next observed minute open, not signal close. Stop gaps use worse opens;
ambiguous stop+target minutes choose stop first and are marked. Completed-bar
adaptive decisions fill later. Gaps force conservative next-observed exits.
OHLC exit times are approximate, not exchange execution timestamps.

REALTIME/ANTICIPATORY require actual ordered tick observations, never reconstruction
from minute highs/lows. Detection cannot fill on its own sequence. Preflight
invalid entries are refused explicitly; already-committed next-tick gap fills
remain recorded and close protectively with costs. Stops cannot widen;
break-even requires its trigger. Research risk/RR caps are not account settings.

Statistics include trade count, wins/losses, gross/net, costs/slippage, expectancy,
profit factor, drawdown, streaks, winners/losers, holding time, R, CT month returns
and session breakdowns. Open profit is not closed net; open entry commissions
affect realized balance and marked equity separately. Returns exclude deposits.
Single-contract replay does not model broker queues, bid/ask, latency or correlated
account allocation. Existing walk-forward uses chronological prefixes; no tuning
or actual strategy ranking was possible without market data.

## Reviewed Calendar Configuration

Investigated maintained calendar support, but did not assume a generic CME equity
calendar exactly matches every supported product and Topstep execution window.
Use official CME product/holiday notices. No brittle yearly table or new unverified
calendar dependency was installed. The optional ignored file is
`data/execution_calendar.json`, with this schema (deliberately expired, synthetic
example; **not a verified exchange session and not installed**):

```json
{
  "schema_version": 1,
  "timezone": "America/Chicago",
  "source_url": "https://www.cmegroup.com/trading-hours.html",
  "product_group": "US equity index futures",
  "reviewed_at": "2020-01-02T07:00:00-06:00",
  "valid_from": "2020-01-02T07:00:00-06:00",
  "valid_until": "2020-01-03T07:00:00-06:00",
  "sessions": [{"open": "2020-01-02T08:30:00-06:00", "close": "2020-01-02T12:00:00-06:00"}]
}
```

Operator must verify actual product dates, closures, maintenance and early closes,
then declare all approved open intervals within coverage with aware timestamps.
Review must be no older than seven days and coverage cannot extend more than
seven days after review. An official URL is provenance, not proof its contents
were automatically verified. Holiday/maintenance gaps are omitted open intervals.
Window intersections can only restrict the original Topstep schedule; entries
stop 15 minutes before reviewed close and flatten is requested five minutes before.
Missing file leaves legacy standard hours unchanged, but **blocks VWAP broker
Practice**. Malformed/stale/future data blocks entries without guessing emergency
flatten from an untrusted schedule. Existing standard flatten remains active.
Approved closed intervals request flatten. Unexpected halts require operator
intervention; this is not a live exchange-status service. No calendar was approved
or installed during this audit.

## Tests and UI Verification

Final exact command `python -m unittest discover`: **264 tests, 0 failures,
0 errors, 0 skipped**, 47.986 seconds. The pre-final
full `python -m unittest discover` run passed 262 tests, 0 failures/errors/skips.
Then added feed-loss and persisted migration regressions; their focused run passed
10 tests, 0 failures/errors/skips. The initial targeted run exposed one empty-frame
timestamp error, fixed before the passing full run; it is not counted as a pass.

`python -m compileall -q goxtrade tests` passed. Explicit
`python -m tests.test_vwap_ema_browser` passed desktop/mobile tabs, responsive layout,
nonblank chart pixels, overlays, markers, levels and retained zoom. It did not
press execution controls. AppTest verifies parameter saving without arming and
rejects omitted commissions before allowing an explicit zero-cost synthetic run.
No placeholder profits are shown as broker results. Existing UI design is retained.

Separate focused command, using `-W ignore::FutureWarning`, ran
`tests.test_phase2_calendar tests.test_phase2_data_and_indicators
tests.test_phase2_execution_safety tests.test_phase2_research_accounting
tests.test_vwap_ema_integration tests.test_vwap_ema_ui`: **62 tests, 0 failures,
0 errors, 0 skipped**, 32.897 seconds. These overlap discovery and are not added
to its count as distinct tests.

New focused modules: `test_phase2_data_and_indicators`, `test_phase2_execution_safety`,
`test_phase2_research_accounting`, `test_phase2_calendar`. Existing indicator,
integration, execution, lifecycle, research and UI regressions remain in discovery.
Streamlit bare-context and pandas legacy-concat warnings are nonfatal; connection,
overflow and launcher messages in tests are mocked test scenarios, not actual
broker connections or worker startups.

## Files and Migration

Modified strategy catalog/config/indicators/cross/runtime/entry confirmation;
signal lifecycle/event persistence; strategy/chart history, TickBuffer and collector;
Practice executor, instrument validation and trading schedule; research datasets,
backtest, paper, metrics/performance; strategy parameter/research UI; related tests
and README/operations/strategy documentation. Added `data/feed_coverage.py`,
`market/calendar_guard.py`, four Phase 2 test modules and this report.

Additive schemas: `strategy_feed_windows`, per-profile `*_entry_events`, nullable
historical `retrieved_at`; new JSON audit/consumption fields. Old records are not
deleted or recalculated. Migration derives consumption aliases from saved evidence;
unresolved old paper consumption blocks new entries for review. Active signals keep
frozen exits when parameters change or current settings become invalid.

## Remaining Issues and Readiness

| Severity | Remaining issue / action |
|---|---|
| Critical | No unresolved confirmed Critical implementation defect identified in this audit; tests cannot establish production safety. |
| High | No real historical/tick performance evidence, provider parity or broker lifecycle validation in this checkout. Obtain validated contracts/date ranges and supervised Practice evidence before promotion. |
| High | No documented stable market event ID: connection windows cannot guarantee no provider replay/volume duplication. Prefer authoritative completed backfill; investigate provider delivery guarantees. |
| High | Shared mini-reference signal management is not exact micro-fill protection parity. Actual broker fills/accounting remain authoritative; backup linked stops are required and software trailing is not broker stop amendment. Supervised fill/protection testing remains necessary. |
| Medium | Calendar is operator-reviewed bounded configuration, not automatically maintained exchange/holiday/halt status. No calendar installed; VWAP broker Practice remains blocked. |
| Medium | Single-contract and conservative OHLC research omits queue/depth/latency and exact intrabar execution time. Intrabar modes need true tick coverage and remain experimental. |
| Low | Existing Streamlit/pandas warnings and legacy records with unknown fee/provenance require interpretation, not invented corrections. |

Ready for disconnected UI/monitoring validation; fresh complete data is required
before live signals. Engine is ready for opt-in forward-paper testing with explicit
costs and actual micro ticks, but no such run was enabled here. **Not promoted as
broker-Practice-ready**: reviewed calendar, explicit isolated account permission,
verified complete feed/session data and supervised fill/protection checks are
blockers. Leader remains prohibited regardless of saved permission lists.

Before any supervised Practice run, preserve local files, verify flat state/OCO,
load validated history, inspect waiting reasons and source expiry, enter costs,
test paper first, and explicitly arm only the isolated Practice account yourself.
Never run the real-order smoke test as part of offline validation.

## Primary Sources

- [ProjectX realtime payloads](https://gateway.docs.projectx.com/docs/realtime/): market trade volume versus quote fields and lack of documented market trade ID.
- [CME trading hours and holiday schedules](https://www.cmegroup.com/trading-hours.html): product-specific schedules requiring review.
- [Maintained market-calendar usage](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html): investigated, not accepted as authoritative Topstep/product parity.
- TradingView and contract specification references are linked in [VWAP_EMA_CROSS.md](VWAP_EMA_CROSS.md).

## Git Delivery

Implementation and regression tests: `66d2e69` (`Harden VWAP execution, data
coverage and simulation accounting`). Documentation follows in a separate commit;
`git log -2 --oneline` identifies both delivered hashes. All work stays on
`feature/vwap-ema-cross`; main is not merged or modified. Local secrets, account
configuration, reviewed calendar and databases are excluded from these commits.
