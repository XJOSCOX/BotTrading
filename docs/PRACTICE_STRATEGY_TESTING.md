# Practice Strategy Testing: Phase 12

Branch: `feature/practice-strategy-testing`. No automatic merge into `main`.
The operator explicitly authorized starting Practice automation after checks pass.
This is session authorization, not a requirement to approve each strategy order.

## Selected Forward Configuration

- Exact configured resettable Practice account, authenticated and checked by the
  existing executor. Never choose another returned account as a fallback.
- VWAP EMA Cross only; actual MNQ December 2026 data and executable contract
  `CON.F.US.MNQ.Z26`; one MNQ per entry. MES/MYM execution is off in this session,
  without overwriting their saved quantities or Leader settings.
- CONFIRMED, completed 3-minute candles, session OHLC4 VWAP, EMA9 Close. Existing
  warmup, signal expiry, optional filters and strategy-specific buffered stop/
  adaptive software exit rules are retained; no fabricated crossovers.
- Existing manager limits are frozen for the session, including USD 75 maximum
  planned trade risk, one position, daily trade/loss-streak controls and explicit
  cost estimates. USD 1 per side is used conservatively where the saved research
  policy had no commission assumption; its existing one-tick slippage estimate
  remains. Stops are not tightened to force a trade under the budget.
- Existing account USD 500 loss lock and its saved balance baseline are unchanged.
  Existing per-run limits and cooldown remain authoritative, including the stronger
  overnight restrictions. Session restart cannot reset daily trade/loss counters.
- Mandatory original broker stop; verified fills/ownership; existing full-position
  close and owned-stop cleanup. Software trails are not represented as broker stop
  amendments. No new live amendments, partial exits or confidence-based sizing.
- Leader is disabled and its settings are compared against the saved pre-start
  snapshot. Starting this session does not start or authorize a Leader trade.

## Existing Components, Not A New Engine

`practice_strategy_testing` is a small session/adapter helper. It calls the
existing pure Strategy Execution Manager and risk policy; `practice_executor`
still owns the atomic job claim, event consumption, account checks, bracket
builder, network submission, protection tracking, exits and reconciliation.

The manager's broker scope remains disabled unless explicitly supplied an armed,
freshly reconciled Practice session. It remains prohibited for Leader. Initial
all-candidate arbitration and a final re-evaluation before transmission prevent
conflicting signals or changed risk/pause state from bypassing selection. A
durable job intent precedes submission; uncertain outcomes pause/retain ownership
instead of submitting again. The ordinary seven strategy definitions are not
rewritten. Other registered strategies use this same adapter when explicitly
selected; they are not claimed to be individually forward-validated here.

Indicator monitoring, entry confirmation and signal exit ticks consistently use
the selected actual micro contract, preserving its canonical crossover identity
through the executor job. Existing account configuration/copy routing is reused.

## Controls

Open Execution with Practice selected. Select one strategy and use **Start
Practice strategy testing**, with the existing exact-account/safeguard confirmation.
The current account, MNQ quantity, signal status, broker position/stop, order
attempts, fills, rejected-signal reasons and realized broker results stay in the
existing interface. No dashboard redesign was performed.

**Stop Practice strategy testing** pauses new entries. It does not flatten an
existing trade or stop its exit management. The existing emergency close control
is separate. Closing the browser does not stop the market/execution/history
workers. Run/Pause is persisted; imported modules and app startup cannot arm an
account. After stopping, explicitly start the next single-strategy test. Existing
Control Center parameters allow later confirmed/realtime/anticipatory selection;
this initial session starts CONFIRMED. Existing positions retain their snapshots.

The reviewed session calendar is a real, previously sourced review, not a
manufactured holiday override. Its current coverage ends October 27, 2026 at
16:00 Chicago time, with maintenance/halt exclusions and earlier Topstep cutoff/
flatten rules still enforced. A later session needs current reviewed coverage;
calendar restrictions are not silently bypassed to force a test order.

## Genuine Prior Broker Evidence

Phase 11 submitted exactly one approved Practice SELL, filled 29,455.00, verified
the owned BUY stop at 29,480.00, and separately closed at 29,462.25. Broker state
was flat with no working orders; reported gross loss USD 14.50 plus USD 0.72 fees.
This was a manual API lifecycle validation, not an automated strategy trade.

The separate Phase 11 diagnostic still conservatively reports pending because its
absolute exit timestamp comparison sees the broker time 1.116 seconds before
local close intent. It was not force-completed. The production executor already
reconciled its job Closed with broker-flat state; this diagnostic is not turned
into another mandatory per-strategy-order approval framework. See
[the broker roundtrip report](PRACTICE_ORDER_ROUNDTRIP.md).

## Historical Validation And Offline Replay

Downloaded actual ProjectX MNQ one-minute OHLCV for October 25 at 22:00 UTC through
October 26 at 19:00 UTC: 1,260 bars, 100% requested open-session coverage, zero
missing/duplicate/invalid/zero-volume candles. Contract expiry metadata was checked
against CME's Micro E-mini third-Friday rule, December 18, 2026 at 08:30 Chicago.
The first unqualified download was retained but not accepted until that provenance
was supplied; no rows were fabricated to fill gaps.

Dataset `ce7f79daac7c2234134120f236ded4093d94aa4bc2e6ea466cc85f961c19abcb`.
Validation Lab run `bbcaa46b11caff161cbb8310c3dba2dba720667617b4299072a529e486e844eb`.

Unchanged buffered-stop strategy produced five crossover candidates and ten
manager decisions (including later fill/preflight checks); all were risk-blocked.
The minimum one-contract structural stop could not fit the existing USD 75 risk
budget. Consequently this run has **zero simulated trades**, not five fills or
evidence of profitability. Structural stops and the budget were not weakened.

Independent checks on these actual bars matched EMA9 Close and cumulative OHLC4
VWAP, and full-source versus prefix-only calculations agreed at a historical
cutoff. Existing causality, direction, expiry, stop, cost and duplicate tests also
run. The existing Offline Replay was stepped ten minutes with broker transport
explicitly denied; its clock revealed only the stepped candles. This proves
playback/isolation, not a completed simulated roundtrip. Replay sessions remain
code-version pinned and may require a new session after the final code commit.

Local replay evidence: `data/verification/phase12-replay-evidence.json`. All replay
results are simulated; none may be added to real broker P&L or order counts.

## Concrete Defects Found And Fixed

- Shadow-only manager was not connected to the executor. Explicit Practice
  sessions now bridge the existing decision engine to the existing transport;
  default broker/Leader authorization is still denied.
- Selecting MNQ previously still calculated and confirmed against mini NQ. Actual
  micro candles/trades and contract-scoped exit ticks now stay aligned, including
  the original crossover identity on the job. An old test fixture used different
  source/execution contracts; its provenance was corrected rather than allowing
  unrelated-contract ticks to manage an exit.
- Manager observation time was captured before reading its quotes, causing a
  newly read quote to appear future-dated. Live evaluation now observes its clock
  after the reads, without accepting stale/future data.
- Fill history depended on the old Streamlit page. The market process now starts
  that same existing read-only history worker, independently of browser state.
- Actual first-start history catchup hit SQLite contention and the generic error
  handler paused entries. Only recognized SQLite busy/locked errors now retry
  without changing the saved Run/Pause choice. Other storage failures still pause;
  failure to write the recovery journal no longer kills the reconciliation thread.
  Uncertain-order job locks are not cleared or retried.
- Rejected-signal UI now reads the actual event `kind`, `time`, `topic` fields and
  filters by account, instead of looking for nonexistent event properties.
- Historical unit tests accidentally read the live operator calendar. Their
  calendar fixtures are isolated; the production calendar was not removed.

## Verification And Forward Outcome

Final complete suite: **614 tests passed in 104.029 seconds**, with no failures or
errors. TypeScript/Vite build and compilation
passed; existing Three.js bundle-size advisory remains. Isolated browser checks
passed six viewports x eight pages, no page errors/overflow, stream recovery and
zero broker writes. Broker-mocked tests cover crossover -> manager -> one MNQ
payload with attached stop, exact account routing, conflicting directions, risk/
loss locks, pause, duplicate prevention, unknown-response locks and retry recovery.

The first authorized live session started through the real authenticated local
API, with the exact account, one MNQ and unchanged Leader/loss baseline verified.
It placed no strategy orders before the transient SQLite contention paused it.
The updater then caught up and observed "No new crossover" on the actual MNQ
contract. After the recovery regression passed, the operator-authorized session
was resumed through the same real local API at October 26, 19:04:57 Chicago time.
Session `d3e7e7be94f54630b0695ac8a9663689` was observed at 19:06:25 CT with entries
enabled, fresh actual MNQ source data, and executor status "Monitoring Practice
positions and new signals." The current 3-minute signal bucket was not yet
available at that observation; authoritative post-reconnect history was refreshed
using the existing read-only backfill path, not synthetic candles.

After the final futures-day counter regression passed, entries were briefly
paused for a verified-flat worker reload. The same authorized configuration was
started through the authenticated API at 19:13:48 CT, session
`74db2b91aecc4c7ba1ed5784073e73c2`. At **19:14:18 CT**, entries were enabled,
the executor was monitoring, actual MNQ data was fresh, and the signal reported
**"No new crossover."** The existing read-only backfill refreshed 1,514 genuine
minute bars after reconnect. Daily trade/loss counters use the CME trading day
and include prior test sessions; restart or Chicago midnight cannot reset them.

All sessions together had **zero automated
strategy order attempts, zero fills/exits and zero realized strategy P&L** at the
observation. ProjectX confirmed zero Practice positions and zero working orders.
Leader remained disabled with byte-equivalent settings, and the saved account
loss baseline was unchanged. The session remains enabled to await the next
genuine eligible signal; no indefinite agent-side polling or synthetic entry is
used. The managed application worker, not an open browser/chat, continues it.

Local genuine evidence is preserved in `data/verification/phase12-session-start.json`,
`phase12-session-resumed.json`, `phase12-forward-observation.json`,
`phase12-session-final.json`, `phase12-forward-observation-final.json`,
`phase12-preserved-controls.json`, `phase12-replay-evidence.json`,
`phase12-unittest-final.log` and `phase12-browser.log`. These artifacts are ignored
local state, not published credentials or account identifiers. Later fills must
be read from the broker/worker; this report does not predict their outcome.

No automated strategy fill, exit, stop verification or realized strategy result
is claimed unless recorded below. Passing mocks and a manual broker trade do not
prove automated strategy profitability. Wide-stop risk rejections, overnight
filters, incomplete history, loss locks, calendar expiry and broker restrictions
remain legitimate reasons not to trade. Do not force a crossover to fill a report.

## Production Path Cleanup: October 26

The experimental adapter was promoted to `practice_automation`. Execution no
longer has a separate single-strategy test selector. It uses Control Center's
saved strategies and sizes, with an exact-account Start confirmation binding the
saved quantities. Legacy API/direct Practice arming cannot bypass the manager.
Indicator mode, timeframe, EMA length and sources are not reset by Start.

An existing session's frozen limits remain authoritative. The verified-flat
deployment resumed the previously authorized one-MNQ session without applying
the pending saved size of three, altering the USD 75 planned-risk ceiling,
resetting the USD 500 loss baseline, or enabling Leader. New quantities require
Pause and an explicit Start. Concurrent edits invalidate authorization instead
of being overwritten. Active maximums and saved settings are displayed separately.

The market worker now performs bounded, read-only seven-day history hydration
and rolling repairs. At 19:54 CT, the NQ and MNQ contract stores each held 6,900
real broker minutes; other monitored contracts were also hydrated. No candles
were synthesized. Session-specific warmups still apply after the evening break.
Historical downloads do not bypass fresh quotes, signal expiry or risk checks.

The exact final rounded bracket risk, estimated costs and quantity are checked
again against manager and account headroom before submission. Unknown broker
outcomes retain durable ownership and cannot be automatically resubmitted.
Existing persisted session/job field names are read for compatibility, not used
to launch diagnostics. Manual roundtrip tools, fixtures and replay are not normal
startup entry paths; their historical evidence and regression tests are retained.

Verification: **621 tests passed in 104.279 seconds**, production frontend build
passed, and headless desktop/mobile navigation, chart-pixel, authorization-dialog
and disposable-database Control Center checks passed with no broker orders.
Two defective tests were isolated from wall-clock session shifts and live account
permission settings. Local deployment evidence is in
`data/verification/practice-production-deployment.json` and
`practice-production-observation.json`.

No automated strategy trade had occurred at that observation. This cleanup does
not establish trading performance or a completed automated broker lifecycle.
The reviewed calendar still requires operator maintenance and currently expires
October 27 at 16:00 CT; it was not auto-approved or bypassed. Planned loss limits
are not guarantees against slippage. These operational limitations remain visible
rather than being removed as "test code."

## Sources

- [CME Micro E-mini expiration](https://www.cmegroup.com/education/courses/micro-e-mini-futures/managing-micro-e-mini-futures-expiration)
- [CME hours and holiday calendar](https://www.cmegroup.com/trading-hours.html)
- [CME Micro E-mini FAQ](https://www.cmegroup.com/articles/faqs/micro-e-mini-equity-index-futures-frequently-asked-questions.html)
- [Topstep permitted hours](https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade)
