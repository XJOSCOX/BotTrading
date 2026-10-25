# Offline Market Replay and ProjectX Diagnostics

## Delivery and Safety

Phase 6 starts from remote `main` **9217ecc** and is delivered on
`feature/offline-replay-diagnostics`. It is not automatically merged into main.
The earlier main-final instruction applied to Phase 5; this new milestone
explicitly requests a new feature branch. Existing branches are retained.

This is offline research and read-only diagnostics, not another strategy or broker
execution path. Installation, opening either page, replaying, restoring, stopping
and exporting never arm Practice/Leader, restart trading workers, reset loss locks,
change account mappings or submit broker orders. Actual broker state, forward
paper, minute backtests and offline replay remain distinct sources.

The running trading workers are intentionally not restarted by delivery. A later
operator-controlled restart is required to load new collector telemetry/recovery
code. Check exposure and protection before deliberately restarting any worker.
Interface-only restarts do not change account Run/Pause state.

## Architecture

The original portfolio backtest loop now accepts bounded resumable checkpoints.
Both full backtests and minute stepping call that same loop, candidate adapters,
Strategy Execution Manager, Portfolio Risk Manager and Trade Management Engine.
Prepared immutable tapes avoid repeatedly validating/copying entire datasets.
Open exposures are copied when resuming; completed journal rows are append-only.
The default forward-paper API keeps its original defensive-copy behavior. The
owned-state optimization is used only inside the private historical loop.

New modules:

| Module | Responsibility |
| --- | --- |
| `goxtrade/replay/replay_clock.py` | Validated presentation speeds |
| `goxtrade/replay/replay_engine.py` | Shared-kernel stepping, accounting, event deltas, code identity |
| `goxtrade/replay/replay_session.py` | Explicit controls, bounded playback, source verification, views/chart |
| `goxtrade/replay/replay_adapter.py` | Actual recorded trade import/reconciliation and tick stepping |
| `goxtrade/replay/replay_store.py` | Versioned isolated session/tick persistence and ownership fencing |
| `goxtrade/diagnostics/projectx_diagnostics.py` | Sanitized read-only configuration/auth/history/feed probes |
| `goxtrade/diagnostics/feed_status.py` | Non-secret collector connection/subscription telemetry |
| `web/src/pages/MarketReplay.tsx` | Native replay configuration, controls, virtual account and journals |
| `web/src/pages/ReplayChart.tsx` | Actual revealed candles/volume/overlays/markers with persistent chart instance |
| `web/src/pages/Diagnostics.tsx` | Native diagnostic center and sanitized export |
| `goxtrade/ui/bot/offline_replay_panel.py` | Legacy access to the same services |

Existing integration points changed: `goxtrade/api/app.py`,
`goxtrade/research/portfolio_backtest.py`, `portfolio_forward_paper.py`,
`managed_positions.py`, `datasets.py`, `backtest.py`, `validation_lab.py`,
`goxtrade/strategies/entry_confirmation.py`,
`goxtrade/execution/projectx_client.py`, `goxtrade/runtime/run_live_market.py`,
`goxtrade/ui/bot/page.py`, `web/src/App.tsx`, `web/src/styles.css`, README and
operations/native-interface docs. Package initializers and dedicated tests are
included. `git diff --name-status 9217ecc..HEAD` is the exact file manifest.

## Historical Data

Reuse Strategy Validation Lab to import genuine minute OHLCV, snapshot existing
canonical history, or explicitly request provider history. Replay does not fetch
data or authenticate automatically. There is no generated-data fallback.

Every source retains its real instrument, actual contract, UTC interval, declared
expiration, provenance and SHA integrity hash. The reviewed exchange calendar,
complete finalized coverage, valid OHLC/tick grids and actual nonnegative volume
gates from Phase 5 remain mandatory. Partial snapshots may only be used through
an explicitly complete selected subinterval. Gaps never become forward-filled
candles. One contract per instrument is enforced; split rollover sessions rather
than fabricating a continuous-contract path.

Bounds: 10,000 minute bars per instrument, 20,000 total minutes, at most six distinct
instruments. At most 500 revealed candles are sent to a chart. Recordings are
bounded to 20,000 trades and a 1.5 MB CSV; split larger recordings explicitly.
These are safety bounds, not a claim of provider retention or entitlement.

Tick CSV columns: `sequence,time,price,volume,contract_id`. Timestamps must be aware
and ordered; source sequences must be positive unique increasing integers. Supply
the genuine source and attest completeness. The aggregate minute OHLCV of the
recording must reconcile exactly to the declared complete Lab snapshot. This
rejects captured fragments and mixed contracts; it is not independent proof that
a user-supplied file is genuine. An explicit captured-trade import reads the
existing local live database in read-only mode, with a two-second query budget,
then applies the same reconciliation. Quotes are never substituted for trades.

## Strategy Compatibility and Causality

All seven original mathematical implementations are reused:

- CRT, RSI Reversal, ORB, VWAP Reclaim and EMA Pullback retain registered 15-minute
  setup rules and original completed multi-timeframe entry confirmation.
- VWAP EMA Cross retains its configured 3-minute default and original evaluator.
- Previous Day Box retains completed previous-session coverage and completed
  15-minute confirmation. No incomplete or older convenient box is substituted.

At a minute open, the engine reveals only earlier completed minute bars, processes
previously selected pending entries at the next observed open, evaluates current
candidates and applies centralized deterministic arbitration/risk controls. A newly
selected candidate cannot fill retrospectively at the price that generated it.
The current bar's high/low/close is processed only at its completed timestamp.
Charts never display unrevealed historical high/low/close/volume.

Recorded-tick mode processes source events in order. At each event it manages
positions/fills, reveals completed minutes, evaluates standard confirmed strategies
at new minute boundaries and evaluates opted-in REALTIME/ANTICIPATORY VWAP events
through the original evaluator. Provisional candles aggregate **only actual trades
already observed**, using the same helper as the existing single-strategy tick
backtest. Observation state and current partial bucket persist across pause/restore.
Intrabar modes cannot be enabled with a minute-only dataset.

Both source sequence and a strictly later timestamp are required for a pending
portfolio fill; same-timestamp later trades do not receive a speculative fill.
Warmup is causal inside the selected interval. The interface does not silently
fetch earlier history; select enough previous-session/warmup data. Missing warmup
is an explicit waiting reason, not permission to invent a signal.

Pure historical confirmation uses an explicit `research` profile rather than
inheriting the active broker environment. Live chart retrieval inside the shared
confirmation module is lazy; offline evaluation can run without even importing
the ProjectX transport module. No replay module imports broker execution controls.

## Virtual Account and Profit Management

The virtual account is identified as simulated USD and has no broker account ID.
Defaults: $50,000 starting balance, $75 planned risk per trade, $150 open/group
risk, one simultaneous position, one contract when affordable, $0.50 commission
per side and one adverse slippage tick. Commission is an explicit user input, not
a claim about the user's broker fees. Zero costs require explicit acknowledgement.

Controls expose initial balance, quantity ceiling 1-4, per-trade/open/group risk,
maximum positions, daily loss, fees, slippage and arbitration. Frozen configuration
JSON exposes existing validated strategy settings and exit-policy options. Reuse
the original policy constraints, including one position per instrument and a
maximum research daily-loss allowance of $500. These settings never resize or
change any actual account. Low risk can reject a candidate instead of tightening
its strategy stop. Correlated exposure, consumed setups, expiration, cooldowns,
reward/risk, confirmation and session gates remain centralized.

The UI shows simulated balance, marked equity, realized/unrealized P&L, planned
and available risk, daily drawdown, consecutive losses, open/pending exposure,
candidate selection/rejection reasons and recent historical events. Full frozen
state is available in the replay JSON export. Equity/fees follow the existing
portfolio accounting conventions, not a separate cash ledger.

Original baseline, fixed targets, break-even, ATR/structure/extreme trails,
profit locks, partial exits and hybrids use the existing Trade Management Engine.
One-contract trades cannot manufacture fractional partial fills. Current/initial
stops, targets, current/max R, MFE/MAE, profit giveback, fees and simulated slippage
are visible in management evidence. Completed episodes preserve management
decisions, target-touch status and final baseline state. The event log includes
signals, selected/rejected candidates, simulated fills/exits, partials, protection
adjustments and target touches when observed by the engine.

A profitable trade that later loses must be assessed from those actual simulated
observations. The comparison action queues the existing ten-policy minute research
comparison using the same frozen source/costs; it does not assert an alternative
would have won. That action is disabled for tick sessions because the minute
comparison is not a tick-policy counterfactual. No new confidence scores or strategy
formulas were introduced.

## Replay Controls and Recovery

Play/Resume are explicit. Pause freezes presentation/processing; Stop freezes the
saved session without inventing liquidation. Step advances one minute or actual
trade event. Step Candle advances a recorded minute's remaining observations.
Restart creates a **new** session; the original history is retained. Select the
actual instrument/contract and start/end interval when creating a session. Speeds
1x/5x/10x/30x/60x/Maximum affect cadence only. Paused wall-clock time is not treated
as market movement. Tick cadence uses actual event-time differences.

`data/offline_replay.db` is separate from `data/research_lab.db` and
`data/live_market.db`. It stores versioned session JSON, cursor/clock, source hashes,
actual contract, frozen strategies/risk/exit policies, virtual exposure, pending
intents, consumed signals, VWAP observation state, decisions, account state, events,
code commit/content hash and optimistic revision. Only `replay-` identities are
accepted. A unique SQLite index permits one active playback across controllers;
atomic revision checks prevent stale controllers from overwriting newer progress.

Playback commits at most five events/candles per short processing turn. Cancellation
is cooperative between turns. After interface/process restart, playback does not
silently auto-run: inspect and explicitly Resume. Persisted progress cannot book
the same fill twice. An unfinished uncommitted batch may be recomputed, but it was
never committed as a separate trade. Code commit/content or source integrity
mismatches refuse continuation; Restart creates a fresh session under current code.
Unknown future schema versions are refused without rewriting saved records.

Up to two prepared tapes are cached; chart reads and responses are bounded. Price
delivery keeps its independent 250 ms native stream and does not include replay
state. Replay polls only its own state at 500 ms; the chart instance/zoom survives
updates and only advances when the cursor changes. Pages do not rebuild the entire
simulation on refresh. Active playback is a bounded background thread, not a new
broker worker. It is not a hard real-time or CPU-isolation guarantee.

## ProjectX Diagnostic Center

Passive inspection never logs in. It reports credential **presence** only, approved
HTTPS provider hosts, profile validity without account IDs/names, contract mappings,
exchange-open state, entry permission separately, connection telemetry, requested
subscriptions, last quote/trade source and receipt timestamps and reconnect count.
Local inspection is bounded to the latest 2,000 events; absent instruments are
unknown, not declared healthy. Unknown collector telemetry stays unknown.

The new collector records subscription requests, not provider acknowledgements.
A subscription invocation failure is distinct from an unclassified hub error.
A socket being connected never proves that data is fresh. Market closure is
reported independently, including modeled exchange holidays; absence of events
during closure is not itself `FEED_STALE` or an API outage. Telemetry is not available
from already-running old collector code until a controlled operator restart.

Authentication requires an explicit button press. Credentials go only to a
validated HTTPS ProjectX/Topstep host; redirects are disabled. The in-memory
diagnostic token is neither exported nor written to replay/session storage.
The diagnostic transport allowlists only login, contract-by-ID and historical
bars, never orders. History first verifies the selected contract ID and tick
size/value against the read-only provider contract response.
Authentication is attempted once, not retried after rejection. A history probe
requires a successful explicit authentication test, exact contract and finalized
past interval of at most 60 minutes. It requests at most 100 minute bars and checks
OHLCV/timestamps/grid. It does not save those diagnostic bars as a validated dataset.

HTTP and documented authentication outcomes become structured codes: `AUTH_FAILED`,
`AUTH_EXPIRED`, `PERMISSION_DENIED`, `RATE_LIMITED`, `HISTORY_UNAVAILABLE`,
`CONTRACT_NOT_FOUND`, `WEBSOCKET_DISCONNECTED`, `SUBSCRIPTION_FAILED`, `FEED_STALE`,
`MARKET_CLOSED`, `NETWORK_TIMEOUT`, `PROVIDER_ERROR`, `MALFORMED_RESPONSE`,
`CONFIG_INVALID` and `UNKNOWN_ERROR`. Failed application-level history responses
without a documented cause remain unknown; no guessed explanation is presented as
fact. Empty bars are history unavailable for that specific request, not an outage.
Raw server messages, credentials and tokens are never echoed. Reports include
timestamps, HTTP status where available, durations, bounded retry counts and
evidence-specific recommendations. Only transient read-only history failures use
up to three attempts with short backoff. 401/403 are not blindly retried.

The existing collector continues transient backoff/reconnect behavior. A confirmed
authentication/permission rejection suppresses repeated login attempts until local
credentials change or the operator deliberately restarts it. Exit-management
threads, account loss locks, uncertain-order handling and existing ownership remain
unchanged. Generic network failures do not reset account state. Diagnostics never
restart or arm any account/worker.

Official references checked for this milestone:

- [API-key authentication](https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key/)
  documents HTTP-200 authentication rejection codes and the login endpoint.
- [Historical bars](https://gateway.docs.projectx.com/docs/api-reference/market-data/retrieve-bars/)
  documents minute aggregation, finalized bars, subscription flag and request cap.
- [Contract by ID](https://gateway.docs.projectx.com/docs/api-reference/market-data/search-contracts-by-id/)
  documents read-only contract identity and tick specifications.

## Validation, Performance and Limitations

Tests use deterministic fixtures, temporary databases and blocked broker transports.
Fixtures and their chart screenshots are not production data or profitability
evidence. The fixture minute replay matches the shared portfolio backtest exactly
after normalizing JSON tuples/lists, including trades, decisions, accounting,
all ten existing exit policies, open state and risk history. Tests exercise
pause/restore/restart, maximum cadence, source/code mismatch, single ownership,
tick reconciliation/sequence, recorded intrabar observation persistence, risk/
conflict rejection, data gaps, calendar closure, sanitization, auth rejection,
bounded retries, CSRF/API isolation, non-signalling Windows process inspection,
legacy rendering and responsive browser controls. Existing strategy-specific tests
remain the mathematical/timing regression coverage.

Minute OHLC does not reveal intrabar order: old-stop-first ambiguity, next-open
fills, OHLC-bound excursions and next-bar protective adjustments remain documented
simulation conventions. Actual ticks can produce different exits/MFE/MAE and timing;
they are not forced to match OHLC results. Portfolio versus single-strategy tick
backtests also have intentionally different arbitration, risk, session and fill
gates. No blanket tick/OHLC equality is claimed.

Measured explicit 10,000-candle **no-eligible-strategy fixture kernel** benchmark:
0.079 seconds preparation, 32.394 seconds full batch, 31.750 seconds in 100
checkpoint batches; final state matched exactly. This excludes real strategy
evaluation, persistence and browser/network latency. It is not a live-trading
latency promise. An earlier run was stopped after exposing excessive history
copying; append-only checkpoint copying removed that confirmed bottleneck.

The UI/browser suite passed at widths 2560/1440/1280/834/390/320, including canvas
pixel checks, stepping, Play/Pause, rejection diagnostics and no account mutations.
Existing Validation Lab, Strategy Manager and Trade Management browser suites also
passed at six sizes. The deployed native-app browser suite passed desktop/mobile
navigation, actual WebSocket delivery, chart pixels, zoom retention, pane resizing
and an unconfirmed authorization dialog, with no mutations or broker orders.

TypeScript/Vite and `python -m compileall -q goxtrade scripts tests` passed. The
entry JavaScript bundle is 96.98 KB gzip; the chart library is split separately.
The final backend suite passed **487 tests in 81.681 seconds**, with no failures,
errors or skips. Final presentation-only changes were followed by another successful
TypeScript/Vite build and six-viewport offline replay/diagnostics browser run.
Existing dependency/legacy Streamlit warnings are not claimed fixed in this phase.

At implementation time, no genuine Lab datasets or recorded replay sessions had
been imported into the actual workspace, and no real-market replay outcome was
produced. Authenticated ProjectX probes/downloads were not run during development.
Actual provider access, subscriptions, expired-contract retention, market-open
freshness and exchange-to-browser latency remain unverified. Import or retrieve
verified real data, review calendar/fees, replay a small known interval and compare
the decisions with source observations before drawing performance conclusions.

## Reviewable Commits

- `41a1958`: isolated replay engine/store, shared incremental portfolio/tick
  helpers, original strategy/profit integrations and deterministic parity tests.
- `528c132`: read-only provider diagnostics, sanitized authentication and collector
  telemetry/recovery safeguards.
- `261f020`: guarded APIs, native/legacy pages, actual-data chart and browser/UI QA.
- `594891b`: undocumented authentication failures remain unknown/retryable rather
  than being misclassified as confirmed credential or permission rejection.
- Final mobile presentation and documentation commits follow these; their hashes
  are supplied in the completion report and Git history.

No automatic merge, provider authentication or broker account activation is part
of this delivery. Next: import a small verified actual interval, replay stepwise,
inspect risk/exit evidence, then explicitly test ProjectX access if required.
