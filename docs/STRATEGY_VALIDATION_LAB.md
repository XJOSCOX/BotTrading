# Strategy Validation Lab

## Delivery Base

Started from the clean, pushed `feature/trade-management-engine` commit `909240e`.
All remote branches were fetched. `feature/strategy-execution-manager` was
`0429744`; Previous Day Box, VWAP EMA Cross and the complete Phase 4 engine are
included. No newer incompatible remote development state was found. Development
began on `feature/market-data-validation-lab`. The user subsequently explicitly
requested **main as the final, consolidated branch**. Older feature branches are
retained for recovery, not deleted or rewritten.

This milestone adds no entry strategy. Research never arms an account, changes an
account risk gate, submits broker orders, or changes copier configuration. The
Strategy Manager remains shadow/research-only and central profit management
remains research/paper-only. Existing execution worker processes are not restarted
as part of interface deployment.

## Architecture and Audit

The existing contract history, finalized-minute validators, CME Equity calendar,
seven-strategy registry/adapters, portfolio arbitration, position risk, reservation
logic, backtesting, exit-policy comparison, forward paper, metrics and UI/API
boundaries were reviewed before integration. The Phase 4 full-file inventory is
preserved in [FULL_SYSTEM_AUDIT.md](FULL_SYSTEM_AUDIT.md). Reproduce a current static
inventory with `python -m scripts.audit_system`; static parsing is not measured
line coverage or proof of production safety.

New modules:

- `data/historical_quality.py`: strict UTC/finalized OHLCV and modeled-session
  coverage reports with explicit review gates.
- `data/history_download.py`: read-only ProjectX adapter, bounded retries and
  resumable daily chunks.
- `data/lab_store.py`: immutable content-hashed research snapshots, indexed range
  queries, atomic chunk/cursor commits, job ownership and schema version 1.
- `research/lab_service.py`: common native/Streamlit service and explicit read-only
  bridge from existing canonical ProjectX historical bars.
- `research/lab_jobs.py`: one explicitly launched research thread plus a durable
  cross-process SQLite claim; no automatic startup jobs.
- `research/validation_lab.py`: reproducible orchestration of existing engines,
  portfolio/cost/exit comparisons, chronological windows and trade inspection.
- `research/market_regimes.py`: causal, descriptive, research-only market labels.
- `research/lab_reports.py`: CSV and escaped standalone HTML exports.
- `ui/bot/validation_lab_panel.py`, `web/src/pages/ValidationLab.tsx`: the same
  research service in the legacy and native interfaces.
- `tests/test_validation_lab.py`, `test_validation_lab_ui.py` and
  `test_validation_lab_browser.py`: deterministic isolated verification.

Existing integration changes include API routes/state, portfolio-backtest progress
and risk history, exit comparison cancellation/progress, native navigation/store,
responsive styling and legacy navigation. Strategy capability parity changes are
listed separately below; they do not modify mathematical entry rules.

## Storage and Isolation

Research uses `data/research_lab.db`, **not the live-feed/account database**. This
uses the existing SQLite approach with WAL, indexed `(dataset,time)` keys,
transactions and bounded queries. A separate file is deliberate: long historical
exports, integrity scans and research writes must not lock tick persistence or
account reconciliation. Research snapshots are not another live-feed source and
are never written into `strategy_historical_minutes` or execution tables.

The explicit saved-history import reads the existing canonical contract store;
it refuses missing retrieval provenance. It creates a versioned research snapshot
without altering those original market records. CSV imports are separately labeled
user declarations. Content identity is a hash of normalized minute OHLCV plus the
metadata identity. Runs include both dataset and engine slice hashes. Integrity
hashes are recomputed in bounded batches before replay; valid-looking tampering
does not silently qualify as the original data.

Different contracts cannot share an unlabeled series. One actual contract per
instrument/run is enforced. No continuous/adjusted contracts, synthetic rollover,
forward-filled gaps or manufactured volume are supported. Raw fixtures live only
in temporary test databases, never production history. Schema versions newer than
the supported version are refused without destructive migration.

CSV dataset export and HTML/CSV run export form a portable logical backup of
research inputs/results. They intentionally do not export the account database.
For an additional offline file backup, stop research jobs and preserve the SQLite
file and any active WAL files consistently; do not copy only a live WAL database's
main file and assume it is complete.

## Provider History

Official specifications reviewed October 24, 2026:

- [Retrieve Bars](https://gateway.docs.projectx.com/docs/api-reference/market-data/retrieve-bars/)
  documents a 20,000-bar maximum and aggregation/partial-bar fields.
- [Rate Limits](https://gateway.docs.projectx.com/docs/getting-started/rate-limits/)
  documents 50 history requests per 30 seconds and HTTP 429 responses.

The adapter requests finalized one-minute bars for one explicitly selected actual
contract, in half-open UTC daily windows: at most 1,440 possible minute timestamps
per request, below the cap. Boundary duplicates are normalized, identical
duplicates counted, conflicting duplicates rejected, and descending provider order
normalized with an audit flag. Each completed chunk and its next cursor commit
together. A failed chunk is retried from the last committed cursor, not skipped.

Incremental extensions reuse matching complete, hash-verified ProjectX snapshots
for the same instrument, contract, expiration and subscription, then request only
the uncovered tail. Original chunk retrieval timestamps and source snapshot IDs
are retained. Unknown/partial/user-imported data is not treated as a verified
provider cache, and a complete cache is verified once per download rather than
rescanning its entire history for every daily chunk.

The existing credential/login client is reused; only authentication and the
read-only `/api/History/retrieveBars` endpoint are used by retrieval. No order,
position, account-mode or copier endpoint is called. HTTP timeout remains bounded
at 15 seconds. There are at most four attempts, exponential backoff, bounded
Retry-After handling and a conservative local history request interval. Auth,
subscription, HTTP status and timeout blockers are sanitized without exporting
tokens or raw authentication responses. Other clients can consume the same
provider rate budget, so HTTP 429 remains authoritative.

Presets are 7/30/90/180 days; custom intervals are bounded to 366 days. These are
**requests, not promised availability**. Retention depth, expired-contract
availability and entitlement are not established by those specifications and are
not assumed. Empty or short returns are saved/reported as unavailable or partial.
The actual contract expiration is explicitly operator supplied, with its
provenance recorded; it is not guessed from a month code or presented as
provider-verified metadata. Tick-history retrieval is not implemented: no ordered
intrabar events are reconstructed from minute OHLC.

Market closure is not an error. Downloads/replay do not depend on live worker
health, current exchange-open status or account execution readiness. Provider
history authorization can still fail while the local application remains online.

## Quality and Eligibility

Reports identify source, instrument, contract, expiration, UTC granularity,
requested and available interval, total/invalid/duplicate/missing/zero-volume bars,
unexpected-session bars, verification date and gap samples. Validation includes
aware timestamps, chronological order, minute alignment, finalized bars, tick grid,
finite positive prices, OHLC geometry, nonnegative finite volume, contract identity
and requested interval boundaries. Zero-volume bars remain visible and flagged;
indicator-specific warmup/volume requirements can still reject a signal.

`CME_Equity` from the existing pinned calendar library supplies modeled sessions,
breaks, holidays, early closes and DST. An operator must review the requested
calendar interval and record a reference. Until then expected-count/coverage
percentage is **withheld**, not labeled verified. Review is an attestation, not
proof that the calendar library matches every exchange/product amendment.
Incomplete or unexpected coverage blocks replay rather than silently shrinking
the requested test interval. A complete subset can be selected explicitly.

States: complete, partial, invalid, unavailable and unsupported. Invalid imports
are rejected atomically. Unsupported resolution is explicitly reported. Old
historical ranges are not mislabeled as a broken live feed.

## Research Workflow

1. Select MNQ/MES/MYM/NQ/ES/YM and its actual ProjectX contract and expiration.
2. Select an interval; review the modeled exchange calendar and record its source.
3. Download history, snapshot existing canonical bars, or import actual minute CSV
   with declared source/volume provenance.
4. Inspect the quality report. Only complete reviewed test coverage qualifies.
5. Select datasets, registered strategies, dates, simulated balance, sizing ceiling,
   explicit commissions/slippage, session, shared risk, arbitration and exit policy.
6. Inspect or edit the frozen research configuration snapshot. This does not save
   strategy permissions or account settings. Existing registered signal intervals
   are preserved; VWAP's supported configurable interval is in its configuration.
7. Run a saved, cancellable historical job, inspect accounting and individual
   trades, compare costs/portfolios/exits and export reports.

Both Practice and Leader views see the identical lab and shared research records.
These are not actual account P&L and are never pooled with broker results.

## Simulation and Comparisons

The lab calls `run_portfolio_backtest`, existing seven canonical adapters and the
Phase 4 central post-entry engine. No parallel entry/backtest state machine was
created. Source histories are finalized and strictly available before each signal
decision. Confirmations/expiration/deduplication, session anchors, previous-session
boxes, actual contract mapping and next-observed-open fills retain their existing
requirements. Ordered-tick VWAP realtime/anticipatory modes fail as unsupported
for minute-only replay. Actual historical micro ticks are not invented.

Entry/exit slippage is adverse, commissions explicit, tick/point values
instrument-specific and initial stop geometry mandatory. Position size is a
requested ceiling subject to original risk/cost and shared portfolio constraints;
it is not a promise to force a quantity through insufficient risk capacity. The
original account $500 protections are not altered. Research has its own budgets.
One/two-position comparisons retain correlated-index/group risk caps.

Stop/target OHLC ambiguity uses stop-first. New management levels cannot invent an
intrabar trail-before-reversal order; completed-structure exits wait for the next
observed price. End-of-range positions remain explicitly open/marked, not
fabricated final fills. Realized and marked P&L, entry fees and hypothetical exit
costs are distinguished. Initial balance is a simulated chart/report baseline,
not an account balance or broker limit.

Ten prespecified exit policies share the same causal candidate tape and costs.
Different holding periods can change later portfolio eligibility. Partial exits
use explicit whole contracts; one-contract partial policies are marked
ineligible for that partial, not split fractionally. Remainder trailing can still
operate. Policy snapshots remain immutable per position.

Portfolio experiments include individual strategies, conservative/first-confirmed/
configured-priority arbitration, one/two positions and a lower risk budget.
Results are chronological account simulations, not sums of independent strategy
profits. Cost sensitivity uses the same dates/configuration with +25% fees and
one extra adverse slippage tick. No historical winner is enabled for execution.

## Regimes and Unseen Windows

Regime labels use only completed prior bars: EMA20/50 spread versus recent range,
relative 14-minute volatility against preceding observations, cash-opening time
and overnight consolidation. Sixty observations are required; insufficient warmup
is labeled. Labels can overlap, so their counts are not additive. They describe
research, do not establish a strategy/regime edge and never affect broker entry.

Chronological 60/20/20 training/validation/test and fixed rolling unseen windows
reuse prior warmup but suppress entries before each selected evaluation boundary.
No parameters or strategy priority are fitted from future results. Configuration
hashes show stability across windows. This is fixed-parameter chronological
validation, **not an automatic optimizer**. Fewer than 30 closed trades is clearly
flagged; 30+ trades still does not imply reliable profitability. Risk-adjusted
statistics remain unavailable rather than reporting an unsupported annualized
Sharpe ratio from a tiny, non-independent trade sample.

## Interface and Reports

Native sidebar: Strategy Validation Lab. Tabs: Datasets, Backtesting, Performance,
Trade explorer, Jobs. The legacy Strategies page exposes the same service.
Charts are built only from saved simulated results: equity, drawdown, monthly
net, profit histogram, strategy/exit/portfolio/session/regime comparisons. Empty
samples show empty states. The explorer includes actual contract bars around the
simulated entry/exit plus fill basis, original stop/target, quantity, costs,
policy, reason, MFE/MAE, giveback and ownership metadata. Inspection is bounded;
it is not a full tick reconstruction.

Signal detection, strategy confirmation, expiry and actual simulated fill time
are separate fields; fill time is not mislabeled as signal confirmation. Modeled
entry-plus-exit slippage is reported descriptively and is already embedded in
simulated prices, never subtracted from P&L a second time.

HTML reports escape source text, include dataset/hash/coverage, code revision,
frozen configuration and costs, period, metrics, open-position accounting,
comparisons and limitations. CSV exports are spreadsheet-safe for externally
supplied formula-like text. No API key, bearer token or account identifier is
needed in these reports. Dataset exports stream batches of 2,000 records.

## Real-Time Operation and Bounds

Live prices are delivered before slower attribution snapshots, on a 250 ms local
WebSocket cadence. Account/alert snapshot cache is one second. An asynchronous
snapshot task cannot hold the fresh-price stream; tested with a two-second
deliberately stalled snapshot. Research job revision messages use that existing
stream; the lab reloads on changes and uses a two-second fallback when the stream
is disconnected. No full-page rerun/fade is used. Drafts survive live updates;
expensive research graphs are not recalculated for each price frame.

This is a UI delivery cadence, not a claim of exchange-to-broker latency. A dead
provider cannot produce fresh prices. Existing source timestamps/freshness and
local connection state remain distinct; stale data must not appear live simply
because the UI is connected.

Long jobs use one explicitly launched research thread, not an always-on service.
Persistent status/progress and atomic chunk cursors survive a restart. No job
auto-resumes at startup. Cancel is cooperative between requests or replay progress
checkpoints. Unknown/interrupted owners require explicit resume after a ten-minute
lease; stale owners cannot commit chunks or overwrite replacement jobs. Completed
results are never replaced by failed or cancelled partial work. Identical frozen
requests/code/dataset identity return the same job identifier.

Storage/downloads are bounded to the requested <=366-day minute interval. Imports
are at most 1.5 MB / 60,000 rows. Interactive replay is at most 10,000 minutes per
instrument and 20,000 total; choose smaller windows for longer stored histories.
Comparisons can be expensive. Arbitrary million-tick replay, multiprocessing
optimization and automatic large-window stitching are **not implemented**.
Streaming export and batch integrity reads avoid unlimited history materialization.

## Account Capability Parity

The user's follow-up explicitly supersedes old Practice-only registry restrictions.
All seven strategies are selectable in Practice and Leader, with the same
parameters, intervals, sizing and research tools. VWAP and Box now have independent
`practice_enabled` and `leader_enabled` opt-ins, default off. Both are visible in
both views. Selection is not Start authorization: each account retains its own
Run/Pause, exact identity, reviewed-calendar, feed freshness, OCO/protection,
exposure, cooldown, loss-lock and reconciliation checks.

Existing config fingerprints without the new Leader permission field remain
compatible; historical snapshots are not rewritten. No stored permission or
account configuration was changed during development. A controlled trading-worker
restart is required to load new execution capability code; this delivery restarts
only the interface, never automatically changes active trading processes. Review
and verify the selected Topstep account and worker state before intentionally
starting any new account/strategy.

## Validation and Genuine Results

Automated tests use deterministic fixtures, temporary databases and blocked
broker transports. They cover retrieval chunks, retry/rate-limit/timeout handling,
deduplication/conflicts, quality, holidays/early closes/DST, integrity, schema,
ownership/restart/cancellation, seven adapters, causal comparisons, costs,
chronological windows, API/CSRF, exports, legacy rendering, profile parity and live
price delivery during slow snapshots. Browser checks exercise both profiles at
six desktop/mobile sizes, real fixture charts, settings and research-only writes.

Final exact suite/build/browser results and commit IDs are recorded in the
completion report and Git history. Earlier intermediate test failures included
old tests enforcing now-superseded Leader prohibition and snapshot-before-ticks
ordering; those assertions were replaced with tests of parity, independent
authorization and price-first delivery, not by removing safety checks.

Verified results for this delivery:

- `python -m unittest discover`: **455 tests in 65.927 seconds**, no failures,
  errors or skips.
- `python -m compileall -q goxtrade scripts tests`: passed.
- `npm.cmd --script-shell=cmd.exe run build`: TypeScript/Vite passed; entry JS
  about 91 KB gzip, chart library separately loaded.
- `python -m tests.test_validation_lab_browser`: passed at 2560, 1440, 1280,
  834, 390 and 320 pixel widths, in both profiles, with temporary fixture data.
- Existing Strategy Manager/Control Center and Trade Management browser suites
  also passed at the same six sizes. The native full-app live-stream/chart suite
  passed after interface-only deployment; no authorization was confirmed.
- Local price-state read benchmark: 20 reads, median 1.118 ms, maximum 2.046 ms
  on this development machine, provider requests explicitly blocked. This is not
  an exchange-to-browser latency measurement or a production load guarantee.
- Read-only inspection found **0 canonical historical minutes and 0 captured
  strategy minutes** in the actual local market database. There were no actual
  provider downloads and no real-market strategy results to rank.

Existing dependency deprecation and bare Streamlit-context warnings remain.
Synthetic fixtures are deliberately confined to temporary databases and ignored
browser screenshots. They are never a fallback in the actual research workspace.

**No authenticated historical download or real-market profitability result was
produced during this implementation.** Official retention/entitlement, source
accuracy and exchange-open end-to-end latency remain unverified. Fixture charts
are not performance evidence. Next: verify provider history access, collect
complete same-contract data, review calendar/fees, run chronological costed
comparisons, then deliberately opt into independent forward-paper observation.
Do not activate broker execution because a backtest happens to be positive.

## Reviewable Commits

- `395358b`: historical pipeline, quality/integrity gates, research store and
  causal validation orchestration.
- `a663e57`: incremental provider-cache reuse, original retrieval provenance,
  distinct signal/confirmation/fill timestamps and modeled slippage reporting.
- `142e0a0`: native/legacy workspace, independent account permission parity,
  price-first real-time delivery, and UI/browser regression coverage.
- The documentation commit follows these; the final consolidated main SHA is
  reported after the remote push is verified.

Get the exact new/modified file manifest with
`git diff --name-status 909240e..main`. Core new files are listed in Architecture
and Audit; existing touched modules include the following:

```text
goxtrade/api/app.py
goxtrade/api/state.py
goxtrade/research/exit_policy_comparison.py
goxtrade/research/managed_positions.py
goxtrade/research/portfolio_backtest.py
goxtrade/strategies/previous_day_box_config.py
goxtrade/strategies/strategy_catalog.py
goxtrade/strategies/vwap_ema_config.py
goxtrade/strategies/vwap_ema_cross.py
goxtrade/strategies/vwap_ema_runtime.py
goxtrade/ui/bot/page.py
goxtrade/ui/bot/previous_day_box_panel.py
goxtrade/ui/bot/vwap_ema_panel.py
goxtrade/ui/control_center.py
tests/test_native_api.py
tests/test_phase2_execution_safety.py
tests/test_previous_day_box_integration.py
tests/test_previous_day_box_safety.py
tests/test_strategy_settings.py
tests/test_vwap_ema_integration.py
web/src/App.tsx
web/src/pages/Controls.tsx
web/src/pages/PreviousDayBox.tsx
web/src/store.ts
web/src/styles.css
README.md
docs/BOT_OPERATIONS.md
docs/NATIVE_APP.md
docs/PREVIOUS_DAY_BOX.md
docs/VWAP_EMA_CROSS.md
```
