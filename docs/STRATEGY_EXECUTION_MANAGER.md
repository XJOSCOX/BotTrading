# Strategy Execution Manager

## Delivery Status

Implemented as **shadow monitoring and isolated research/paper**, not as a broker
cutover. `evaluate(..., scope="broker")` cannot authorize a submission. Broker
reservations are also prohibited. Existing order selection, reconciliation, arming,
protective orders, emergency controls, ownership and the $500 lock are unchanged.

This is the conservative milestone explicitly permitted in the Phase 3 request.
It does **not** claim that the existing Practice/Leader submit loop now uses the
manager. No account was activated, no broker order was sent, no credentials were
changed and no funded-account settings were copied between profiles.

## Base and Branch Audit

Remote branches were fetched before edits. Remote `main` was `a0d7fbe` and
`feature/vwap-ema-cross` was `20ab748`. There was no remote Previous Day Box branch
or newer integration branch. The complete locally committed
`feature/previous-day-box` at **`51bc787`** was selected; its worktree was clean.
It contains all seven strategies, the native UI and the prior validation work.

New branch: **`feature/strategy-execution-manager`**. The first implementation
commit is `374c447`; the UI integration is `555fdaa`. The final safety and
validation/documentation commit is in this branch's log. Nothing is merged into `main`, and no push was requested in
this milestone. The unpublished Box implementation was preserved, not invented
or replaced.

## Execution Path Audit

The existing paths were reviewed before refactoring:

- `practice_executor.py` is the shared account-isolated broker implementation.
  Its cycle reconciles known intents/orders/positions and stop protection before
  considering new entries. It retains loss-gate, pause, schedule, feed, strategy,
  confirmation, conflict, volatility, overnight, contract, exposure and quantity
  checks, then atomic job claim and repeated send-boundary preflight. Uncertain
  submissions are never blindly retried. Existing alert-ID iteration remains.
- `leader_worker.py` runs that executor with a fixed Leader identity in an
  isolated process; `leader_execution.py` sends explicit commands to it. Neither
  path was changed or invoked for trading during this work.
- `bot_controls.py` stores account-specific execution choices. Shared strategy
  parameters and intervals remain in `strategy_settings.py`. Monitoring is not
  account arming. The lifecycle preserves source alerts and trade exit ownership.
- `bot_monitor.py` evaluates strategies and persists monitoring records; runtime
  adapters preserve VWAP EMA Cross and Previous Day Box. No manager submission
  hook was inserted into this loop.
- `entry_confirmation.py` verifies each strategy's current entry conditions.
  Overnight and volatility checks remain authoritative at the existing broker
  boundary. `trading_schedule.py` and `calendar_guard.py` can restrict entries and
  enforce close buffers; the new historical path uses the exchange calendar
  offline, not a claim of reviewed live broker preflight.
- Existing independent `backtest.py` and `forward_paper.py` remain intact. Their
  strategy evaluators/exit functions are reused; their accounting is not combined
  with the new portfolio population. `live_store.py` remains the actual-tick
  source and existing SQLite connection provider.

## Architecture

`Market observations -> strategy adapters -> immutable candidates -> eligibility
-> instrument conflicts -> portfolio risk -> simulation selection`

For a future broker cutover, a selected candidate would additionally need atomic
account capacity reservation, refreshed broker reconciliation and **all** existing
send-boundary checks before the existing submission function. That final link is
not enabled here.

Modules:

- `execution/trade_candidate.py`: immutable candidates, explicit legacy adapters,
  actual-instrument validation, stable identities and credential-safe JSON.
- `execution/execution_policy.py`: validated research-only configuration.
- `execution/strategy_manager.py`: pure deterministic eligibility and selection.
- `execution/signal_arbitration.py`: batch instrument conflict resolution.
- `execution/portfolio_risk.py`: account/group planned-risk authorization.
- `execution/execution_decisions.py`: structured results and explicit check scope.
- `execution/signal_reservations.py`: transaction-safe research reservations,
  audited recovery and reproducible decision snapshots.
- `execution/manager_service.py`: local shadow read model, separate settings,
  saved research and compare-and-swap paper persistence; no broker client calls.
- `research/portfolio_backtest.py`: causal multi-instrument competition and
  chronological fixed-policy validation.
- `research/portfolio_forward_paper.py`: shared portfolio accounting kernel.
- `runtime/manager_paper_worker.py`: explicitly started independent paper process
  with an OS lock. It cannot submit orders or arm an account.

## Candidate Contract

`TradeCandidate` is frozen and contains candidate/setup identity, canonical strategy
and display name, exact account/profile, actual executable contract/instrument,
direction, interval/classification, created/confirmed/expiry timestamps, entry
reference/current executable price, original structural stop/target, ownership
management mode, source session, quote timestamp, confirmation/history/permission
facts and frozen configuration/evidence/risk JSON. Reward/risk is derived from the
current executable geometry. No price or account identity is inferred.

IDs include strategy, source setup, account/profile, actual contract and direction;
price changes do not create a new identity. Existing source consumption keys are
preserved. Legacy adapters are additive and do not rewrite stored alert history.
Incomplete watch signals remain watch-only. Missing session or frozen adaptive/
trailing ownership fields cannot authorize an entry.

All seven strategy routes are present: CRT, RSI Reversal, ORB, VWAP Reclaim, EMA
Pullback, VWAP EMA Cross and Previous Day Box Reversal. Categories, data needs,
entry policy, execution profiles, correlation group and default priority live in
the registry. Categories do not grant permission or imply higher expectancy.

## Eligibility and Arbitration

The pure evaluator consumes supplied state and has no network/database dependency.
It checks registered identity, immutable ID consistency, account/profile, enabled
research participation, symbol/contract match, mode/interval, observable timestamps,
bounded expiration, fresh executable price and portfolio state, complete history,
confirmation, explicit strategy eligibility, positive tick-grid stop/target
geometry, reward/risk, consumed setup, pause/emergency/uncertainty, session and risk.
Malformed or contradictory input fails closed.

Results are `ELIGIBLE`, `REJECTED`, `EXPIRED`, `CONFLICTED`, `RISK_BLOCKED`,
`DATA_UNAVAILABLE` or `EXECUTION_DISABLED`, with a reason. Every record includes
decision group/time, strategy/candidate, conflicts/support, selected identity,
planned risk, available budget, quantity, policy version, mode, profile and status.
Historical/paper results explicitly say broker checks were not performed.

Modes:

- **Conservative** (default): opposite eligible directions block the entire
  underlying instrument. Same-direction candidates select one owner using the
  configured priority, confirmation timestamp, then candidate-ID tie-break.
- **First confirmed**: confirmation timestamp first, then explicit priority and
  stable candidate identity. Never database alert order.
- **Configured priority**: explicit preference, then confirmation/identity. This
  is not a performance claim.
- **Evidence research**: fail-closed/unavailable until a separately reviewed,
  genuinely out-of-sample ranking artifact exists. No invented metrics are used.

All implemented modes retain the opposite-direction block. Supporting candidates
remain independent; stops and targets are never blended. The selected owner keeps
its exit configuration. Existing same-instrument exposure blocks additional entries,
no automatic reversal occurs, and opposite index exposure is not treated as a
perfect hedge. If the selected owner's risk cannot fit, the batch records a risk
rejection; there is no hidden fallback to a different strategy's stop.

## Risk Policy

Research defaults: $75 planned risk/trade, one simultaneous position, one position
per underlying instrument, at most four contracts, one requested contract and a
five-minute post-close delay. Paper mode is **off**. Fees are **unset**, not assumed;
simulation requires explicit fees, and zero fees require acknowledgement.

`price risk/contract = abs(executable entry - structural stop) * point value`

`planned trade risk = quantity * (price risk + 2 * fee/side + 2 * slippage ticks *
tick value) + protective buffer`

This is planned stop exposure, not worst-case loss. Stops may gap, slip or fail.
Frozen/current policy are both checked before a pending paper fill; the stricter
permission/capacity wins. The original stop is never tightened to fit a budget.
Quantity may be reduced explicitly; if one contract cannot fit, reject.

Controls include per-trade/open risk, daily realized loss, daily loss with negative
unrealized P&L, position/contract limits, daily trade count (including pending
capacity), consecutive losses, post-close cooldown and optional strategy budgets.
Research loss caps cannot be raised above $500; no manager setting can acknowledge,
reset or modify the existing persistent account loss gate.

NQ/MNQ, ES/MES and YM/MYM share the registry's `US_EQUITY_INDICES` group; standard
and micro versions share an underlying key. Group position count, planned risk,
gross dollar notional and absolute signed net dollar notional are capped. Opposite
exposure is still blocked rather than counted as a risk-free offset. Group names
are registry metadata, extendable for new instruments; this is not a rolling
correlation model or an empirical hedge estimate.

## Reservations, Persistence and Recovery

Research `reserve()` uses `BEGIN IMMEDIATE`. Existing persistent reservations are
added to supplied owned exposure before evaluating the entire new batch; capacity
check, decision snapshots and reservation insertion commit together. A partial
unique index prevents two active reservations for the same account/profile/
underlying, and candidate identity is unique within an account/profile. Busy SQLite
transactions cannot authorize an order. Schema initialization refuses an active
caller transaction instead of implicitly committing it.

Lifecycle: `reserved -> intent -> confirmed / partial / rejected / unresolved`,
then an observed/audited terminal close or rejection. Intent/partial/unresolved
states block new capacity. There is no timeout release and no restart-based reset.
An uncertain result is not a failed order. Transitions require a reason; confirmed
or partial simulation observations require a fill identity. This is a research
state machine, **not** an implemented real-broker recovery command.

Tables are `manager_settings`, `manager_decisions`, `manager_reservations`,
`manager_reservation_audit`, and `manager_simulation`. Settings do not share keys
with account controls, credentials, loss gates or strategy-level paper history.
Snapshots preserve candidate/state/policy where valid; credential-shaped JSON is
rejected/redacted. Do not place credentials in free-text evidence/recovery reasons.

Portfolio paper has its own persisted pending-capacity/open-position state. A
compare-and-swap transaction prevents competing workers from replacing a newer
state or duplicating fills. Its independent OS-locked worker serializes normal
operation. It does not reserve capacity in the broker loop.

## Portfolio Backtest

Actual same-contract finalized minute datasets are validated separately by
instrument, tick grid, provenance, unique timestamps and completeness. At each
timestamp the simulator advances owned positions, exposes only completed prior
bars to **every selected strategy**, evaluates candidates together, applies shared
policy/risk and waits for a later actual observed open to fill pending selections.
Fill price/contract, freshness, permission, geometry and risk are checked again.

Commission and adverse slippage are explicit. Ambiguous same-bar stop/target hits
use stop-first handling. Gaps close at the next observed open and are flagged;
there is no synthetic continuous rollover. Frozen strategy exit functions update
only from completed data and affect future observations. Open positions remain open
at the dataset boundary rather than receiving an invented closing price.

Saved outputs include data hashes, configuration/policy, candidates/decisions,
trades, open/pending state, net/costs, drawdown, win rate, expectancy, profit factor,
strategy/direction/session/month breakdowns and rejection/conflict statistics.
This is one competing portfolio, not added independent strategy P&Ls.

`compare_portfolios()` compares prespecified modes and individual participation.
Different risk/position/group constraints can be saved and rerun as explicit
scenarios. `walk_forward()` uses chronological test folds, preceding causal warmup
and a fixed policy; it does not fit priorities or parameters from future outcomes.
Minute replay supports confirmed indicator mode only; realtime/anticipatory modes
require recorded intrabar data and are rejected by this portfolio minute adapter.

## Forward Portfolio Paper

Enable separate portfolio paper entries only with explicit cost assumptions, then
use **Start paper worker**. The worker is independent of Chrome and the interface,
not auto-started by a page visit, account selection, app import or saved policy.
Disabling paper entries cancels pending fills while owned paper exits continue;
the worker exits once disabled and flat. Pausing paper does not pause a broker.

Only actual sequenced same-contract trade observations can fill a pending entry,
strictly after selection. Initial startup starts at the current tick cursor rather
than replaying pre-enable history. Duplicates, future ticks, excessive delivery
delay, backward observations and ticks older than an already-decided snapshot are
rejected/audited, never inserted retrospectively as fills. Pending expiration is
audited; no tick means no fill. Old-contract owned exits remain observed after
rollover; current-contract new entries remain subject to shared capacity checks.

Frozen owner stops/management remain on existing positions if participation,
quantity or current strategy parameters change. Current permission and tighter
research limits are rechecked for new pending fills. The paper ledger is entirely
separate from existing per-strategy paper and broker fills/results.

## UI and Profile Parity

Native **Strategy Manager** and the Streamlit Strategies **Strategy Manager** tab
use the same services/policy. They expose overview, candidates, precise decisions,
priorities, monitoring/research participation, permitted instruments, per-strategy
budgets, research portfolio limits, historical comparisons, separate paper state
and decision/reservation journals. The native view refreshes locally without a
page reload and preserves unsaved research edits.

Both Practice and Leader now expose the same complete strategy catalog, shared
intervals, VWAP parameters, Box settings and manager controls. The Control Center
no longer hides restricted strategies from Leader. Broker entry choices remain
account-specific and restricted choices are visible but disabled. Shared
monitoring/parameters do not copy Practice arming, sizing or permissions to Leader.
The existing Practice-only VWAP/Box restrictions are not bypassed for UI parity.

Shadow reads use local monitoring, active alerts, actual micro trades, strategy
confirmation, account controls, persistent loss state and broker-health snapshots.
Missing/stale health, missing loss metadata or unresolved account exposure cannot
be treated as verified flat/risk-free state. Existing open-account stop risk is
not guessed from a watch alert. Explicit **Record shadow decisions** persists a
snapshot; automatic display refresh does not arm, submit or record a broker fill.

## Validation

The regression suite passed **404 tests in 53.497 seconds**, with no failures,
errors or skips and existing strategy/executor tests preserved. Tests cover all seven normalization routes, strict envelope validation,
same/opposite signals, stable timestamp selection, costs/micro values/sizing,
correlated exposure, lock/cooldown, concurrent reservation capacity, contention,
restarts, uncertain/rejected/partial outcomes, missing protection/ownership, pause,
rollover, weekend/early-close calendars, causal portfolio competition, future-data
mutation, stop-first/gap handling, next-tick paper fills, late observations,
compare-and-swap, disabled/stricter pre-fill policy, expiry auditing and API
isolation. All broker access is mocked/blocked.

Production TypeScript/build passes. Browser QA covers manager tabs and shared
Practice/Leader strategy/interval/parameter controls at 2560, 1440, 1280, 834, 390
and 320 pixel widths, actual API saves against temporary SQLite, reload persistence,
paper-off defaults, JavaScript errors and overflow. The pre-existing Control Center
browser suite also passes. UI fixture screenshots are under ignored
`data/verification/manager-*`; they are not real trading results.

On October 24, 2026, actual strategy history tables contain **0 historical minute
rows and 0 captured strategy minute rows**. Therefore no genuine portfolio
profitability, empirical correlations or out-of-sample ranking is claimed. Market-
open feed, real-data studies, reviewed calendar/account connectivity and actual
broker reconciliation cannot be certified from deterministic tests.

## Readiness and Remaining Work

- **Monitoring:** ready for local shadow evaluation; requires fresh existing feed
  and strategy results to produce meaningful candidates. Incomplete candidates
  remain explicit watch-only rejections. Persistent shadow snapshots are operator-
  requested, not a new automatically enabled broker worker.
- **Forward paper:** implemented, tested and off by default. Requires complete
  same-contract strategy histories, current observations and explicit costs. Start
  its worker deliberately after reviewing research settings.
- **Broker execution:** cutover **not ready / prohibited**. Before any replacement,
  map exact account-owned positions and verified protective orders into immutable
  risk snapshots; reconcile existing jobs/consumption with persistent reservations;
  implement fresh account-wide realized/unrealized P&L and counters; repeat every
  legacy schedule, reviewed-calendar, overnight, volatility, loss, pause, contract,
  stop and send-boundary check; test rejection/timeout/partial/gap races against a
  broker sandbox; conduct shadow comparison; then separately review and authorize
  Practice. Leader needs separate review. Do not remove old job locks beforehand.

Known limits: conservative planned-risk estimates, no order-book/queue/bid-ask fill
model, no OHLC intrabar path reconstruction, strict capture completeness can
suppress valid setups, no automated priority optimization/OOS ranking, no empirical
rolling-correlation estimator, no automatic hedge/reversal/stop blending and no
broker-integrated reservations. Paper audit arrays are retained in its separate
state and can grow; long-duration archival/compaction needs a separately verified
retention policy. Historical comparisons are bounded to 20,000 interactive source
minutes to control synchronous work, not a large-scale research scheduler.

Recommended next steps: restore provider access, acquire complete actual-contract
datasets, review session/calendar coverage, run prespecified costed portfolio
comparisons and chronological folds, observe shadow decisions in an open session,
then explicitly run forward paper. No result here proves profitable trading.

## File Manifest

Added application modules:

```text
goxtrade/execution/execution_decisions.py
goxtrade/execution/execution_policy.py
goxtrade/execution/manager_service.py
goxtrade/execution/portfolio_risk.py
goxtrade/execution/signal_arbitration.py
goxtrade/execution/signal_reservations.py
goxtrade/execution/strategy_manager.py
goxtrade/execution/trade_candidate.py
goxtrade/research/portfolio_backtest.py
goxtrade/research/portfolio_forward_paper.py
goxtrade/runtime/manager_paper_worker.py
goxtrade/ui/bot/strategy_manager_panel.py
web/src/pages/StrategyManager.tsx
```

Added tests and documentation:

```text
tests/manager_fixtures.py
tests/test_execution_manager_safety.py
tests/test_execution_reservations.py
tests/test_portfolio_backtest.py
tests/test_portfolio_forward_paper.py
tests/test_portfolio_risk.py
tests/test_signal_arbitration.py
tests/test_strategy_manager.py
tests/test_strategy_manager_ui.py
tests/test_strategy_manager_browser.py
docs/STRATEGY_EXECUTION_MANAGER.md
```

Modified existing files:

```text
README.md
docs/BOT_OPERATIONS.md
docs/NATIVE_APP.md
goxtrade/api/app.py
goxtrade/strategies/strategy_catalog.py
goxtrade/ui/bot/page.py
goxtrade/ui/control_center.py
web/src/App.tsx
web/src/pages/Controls.tsx
web/src/styles.css
```
