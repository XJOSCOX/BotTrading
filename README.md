# GoXTrade

## Current Release

The consolidated release is maintained on `main`. See
[Practice Release Audit](docs/PRACTICE_RELEASE_AUDIT.md) for the seven-strategy
Practice configuration, verified fixes, validation evidence and operating limits.
Earlier phase/branch references below are historical delivery records, not
instructions to run another branch or authorize trading.

## Practice Operations

See [PRACTICE_OPERATIONS.md](docs/PRACTICE_OPERATIONS.md) for Practice-only rollout,
saved-setting preservation, broker protection, recovery and operating checks.
Diagnostics now separates passive Practice execution health from strategy/data
readiness. Source-build checks prevent authorization through an outdated worker;
unknown process status never authorizes a duplicate worker or removes registration.
These checks do not certify profitability or future unattended broker behavior.

## Operational Acceptance

Phase 8 is delivered on `feature/operational-acceptance`, without automatic merge
or trading activation. Diagnostics now shows passive strategy, research and
account-safety evidence with explicit unknown/stale states. See
[OPERATIONAL_ACCEPTANCE_REPORT.md](docs/OPERATIONAL_ACCEPTANCE_REPORT.md) for
the verified software tests, confirmed fixes and actual provider/data blockers.
Offline success does not establish real historical, Practice or Leader readiness.

## Pre-Deployment Hardening

Phase 7 is delivered on `feature/system-hardening`, based on Phase 6, without an
automatic merge or account activation. It adds confirmed error-handling, restored
risk-state, broker-response/protection and replay/UI reliability repairs, plus
isolated lifecycle/failure tests. See
[PRE_DEPLOYMENT_AUDIT.md](docs/PRE_DEPLOYMENT_AUDIT.md) for exact evidence,
measurements and remaining gates. Passing offline tests is not live broker
certification. Practice and Leader execution still require independent validation.

## Offline Replay and Diagnostics

Phase 6 is delivered on `feature/offline-replay-diagnostics`, without automatically
merging into main. Open **Market Replay** for causal historical playback, isolated
virtual trading, frozen risk/exit settings and inspectable decisions. All seven
existing strategies and ten existing exit-policy comparisons are reused.
Minute OHLCV and reconciled actual trade recordings remain distinct simulations.

Open **Diagnostics** for passive feed/configuration evidence and explicit read-only
ProjectX authentication/history tests. No research or diagnostic action starts an
account or submits orders. Saved data can replay without ProjectX. See
[OFFLINE_REPLAY_AND_DIAGNOSTICS.md](docs/OFFLINE_REPLAY_AND_DIAGNOSTICS.md) for
controls, persistence, causality, safety boundaries and measured limitations.

## Strategy Validation Lab

The Phase 5 consolidated delivery is on `main`. Open **Strategy Validation Lab** for
read-only contract history, quality/coverage reports, immutable research datasets,
costed strategy/exit/portfolio comparisons, chronological unseen windows and
exportable simulated results. Research is isolated from the live-feed database.
Practice and Leader have identical strategy capabilities with independent
authorization; no account is started by research or installation.

See [STRATEGY_VALIDATION_LAB.md](docs/STRATEGY_VALIDATION_LAB.md) for provider limits,
supported periods/instruments, reproducibility, real-time operation and unresolved
real-market validation. A positive backtest does not authorize broker trading.

A local React/TypeScript trading workspace backed by FastAPI, with market charts,
strategy alerts, account statistics, and opt-in Topstep execution. Streamlit remains
available as a legacy fallback; the new interface does not require it.

## Local Configuration

Install dependencies with `python -m pip install -r requirements.txt`.
For a new checkout, open **Connection** to enter credentials, then **Accounts** to
configure verified execution identities. No account is armed by setup. An existing
ignored `goxtrade/config/execution_target.py` remains the fallback for older installs;
its example identities are placeholders, not trading accounts. Optional copy-role
labels use `goxtrade/config/copy_accounts.json`; these labels do not configure or
verify broker copying. Never overwrite existing local configuration during updates.

When updating an older installation, move its existing `execution_target.py` and optional `copy_accounts.json` from the project root into `goxtrade/config/`. Preserve the existing `.env` and `data/` folder in the project root.

Credentials, account configuration, databases, logs, and trading history are excluded from Git. Do not overwrite existing local configuration when updating an installation.

## Run

On Windows, double-click `start_app.cmd`, `GoXTrade.cmd`, or the **GoXTrade** desktop
shortcut. Both CMD files open the same persistent control menu and local interface
(normally http://127.0.0.1:8504). Choose **2** to restart the interface without closing
the CMD or interrupting trading workers. Closing Chrome or the menu leaves the app
running. Stopping trading workers is a separate, broker-flat-guarded menu action.
Nothing is installed to start automatically with Windows, and starting the interface
never arms execution or starts trading workers.

See [NATIVE_APP.md](docs/NATIVE_APP.md) for setup, menu commands, security and tests.

To run Streamlit directly during development:

```powershell
C:\Python313\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

## Project layout

```text
app.py                  Legacy Streamlit entry point
start_app.cmd           Persistent interface control menu
GoXTrade.cmd            Alias for the same menu
web/                    React/TypeScript interface, Vite build and page modules
goxtrade/
  api/                  Loopback FastAPI endpoints and WebSocket snapshots
  bot/                  Monitoring, alerts, audit, and replay
  config/               Local account configuration and its example
  data/                 Storage and price-history code
  execution/            Broker API, orders, accounts, and reconciliation
  market/               Sessions and execution schedule
  research/             Historical and forward-paper simulations and comparison
  runtime/              Launchers, process control, and live feed
  strategies/           Strategies, confirmation, stops, and entry guards
  ui/                   Pages, shared styles, and chart assets
tests/                  Offline tests and optional browser checks
scripts/                Diagnostics and explicit broker smoke test
docs/                   Operations documentation
data/                   Local databases, saved history, logs, and PID files
```

Run commands from the project root. Background workers and diagnostics use package
imports; for example, `python -m scripts.check_executor_idle`. Native interface control:
`.venv\Scripts\python.exe -m goxtrade.runtime.native_app start` (or `restart`, `stop`,
`status`). Legacy `manage_app` controls have a broader process scope.

## Current Scope

- Dashboard: executed-trade statistics, current/archived account scope and research comparison.
- Charts: live candlesticks, volume, RSI, multi-chart views and retained zoom.
- Strategies: monitoring, evidence, alert history, trade review and research.
- Control Center: strategy selection, quantities, re-entry delay and candle/exit settings.
- Execution: explicit Practice/Leader authorization, pause, protection and actual fills.
- Accounts: enabled-account directory and guarded account replacement.
- Connection: API credentials, worker controls and contract mappings.
- Research: source-separated saved runs and explicit actual-minute-CSV backtests.

The interface shares GoXFinance's charcoal/sage palette and Inter/system font stack.
Legacy Market/Bot/Live links redirect to Charts/Strategies/Execution. See
[WORKSPACE_GUIDE.md](docs/WORKSPACE_GUIDE.md) for configuration and account maintenance.

See [BOT_OPERATIONS.md](docs/BOT_OPERATIONS.md) for strategy rules, safeguards, and limitations. New setups support 5/10/15-minute stop management. Automated trading can lose money; test in Practice before enabling a Leader account.

## Previous Day Box Reversal

The additive `previous_day_box` strategy uses completed previous-session high/low,
configurable discount/premium zones and completed 15-minute wick, sweep or causal
structure confirmation. Monitoring defaults on; forward paper and broker account
opt-ins default off. Practice and Leader offer the same capabilities with independent authorization. See
[PREVIOUS_DAY_BOX.md](docs/PREVIOUS_DAY_BOX.md) for session/calendar requirements,
chart/settings/research integration, safeguards, validation and deployment limits.
Strategy watch always lists registered strategies, even without worker results.

## Phase 2 Validation

See [PHASE2_VALIDATION.md](docs/PHASE2_VALIDATION.md) for confirmed defects, regression
coverage, calendar configuration and remaining deployment blockers. Research now
requires an explicit commission or acknowledged zero-cost sensitivity scenario.
VWAP broker execution additionally requires a fresh operator-reviewed CME calendar;
missing calendar information blocks this strategy, never grants permission.
No real-market profitability or TradingView feed parity has been established.

## VWAP EMA Cross

The new strategy defaults to completed **3-minute** candles, **EMA9 Close**, and
**OHLC4 session VWAP weighted by actual traded volume**, anchored at 17:00 Chicago.
Existing five strategies retain their 15-minute signal rules. The strategy registry
declares independent timeframes, data requirements, canonical IDs and execution eligibility.

Open **Bot > VWAP EMA Cross** for status/chart, validated Parameters, historical
Backtest and source-separated Comparison. Monitoring defaults on; forward-paper and
broker opt-ins default off. Saving settings never arms an account. Practice and
Leader expose identical strategies and parameters with independent opt-in and Start authorization.

Historical research accepts actual timezone-aware minute OHLCV CSV or saved
contract-specific data. Intrabar modes additionally require ordered actual trade
observations; no intrabar signals are invented from OHLC. Comparisons keep historical,
forward-paper, broker Practice and Leader P&L separate. No verified profitability is
claimed. Read [VWAP_EMA_CROSS.md](docs/VWAP_EMA_CROSS.md) for formulas, account opt-ins,
data coverage, risk snapshots, schema additions, fill assumptions and known limitations.

Run offline unit tests with `python -m unittest discover`. Browser checks live in `tests/` and require a local app and Playwright with Edge; run them as modules, such as `python -m tests.test_leader_browser`. They do not submit orders.

## Practice Execution Validation

Run `python -m scripts.practice_execution_validation` for an explicit read-only
ProjectX preflight. It validates the designated identity, exposure, persistent
loss gate, MNQ contract specifications, schedule, live bid/ask/trade freshness
and historical bars. Sanitized results are saved under ignored
`data/verification/practice-execution-readonly.json`; blocked readiness returns
a nonzero status. Imports and automated tests never make real broker requests.

The default and `--request-order` remain read-only. Phase 10 adds explicitly gated
`--mode` actions for operator-reviewed provider evidence, calendar review, one-MNQ
proposals, separate interactive entry/full-close approvals and reconciliation.
Nothing submits automatically. A simulated account or PRAC name alone does not
establish Practice category. The obsolete `scripts.practice_smoke_test` alias has
been removed; use the canonical diagnostics command instead.
Read [Controlled Practice Round Trip](docs/PRACTICE_ORDER_ROUNDTRIP.md) before
using any explicit order mode. Leader is excluded, and no account or strategy is
armed by this workflow.
See [Practice Execution Validation](docs/PRACTICE_EXECUTION_VALIDATION.md) for
actual provider evidence, mocked coverage and outstanding execution blockers.

## Practice Automation

Execution has an explicit **Start Practice automation** control. Save strategies,
micro sizes and cooldown in Control Center, then review the exact account and
saved quantities in the Start confirmation. The shared manager and protected-order
executor apply the existing risk limits; no per-order approval is needed. Starting
does not reset VWAP/EMA parameters or force one strategy, timeframe or size.
Running sessions keep frozen settings; Pause and Start explicitly to adopt edits.
The interface distinguishes active size limits from pending saved settings.
Stopping entries
leaves open-position management active; no per-order confirmation is required
once the operator starts the session. Leader is never activated by this control.
The account loss baseline and active limits are not reset by startup. See
[Practice Strategy Testing](docs/PRACTICE_STRATEGY_TESTING.md) for actual versus
replay evidence, configuration, controls, limits and current results.

The market worker recovers genuine contract-specific history independently of
the browser: bounded seven-day startup hydration (including weekends), followed
by rolling repair requests. Missing provider bars remain missing, never fabricated.
Legacy Practice arming is disabled; only the manager-controlled Start can arm it.
Regression fixtures, offline replay and manually invoked broker diagnostics remain
development tools, not automatic entry paths. Do not delete the regression suite.
The final rounded order is checked against planned-risk and remaining account
budgets before transmission. Broker gaps and slippage can still exceed estimates.
The reviewed exchange calendar must be maintained; expiry deliberately blocks
entries. No automatic calendar approval or loss-baseline reset is performed.

## Safeguards

Use **Settings > Safeguards** for each account's cumulative loss lock, maximum
contracts per symbol, planned trade-risk ceiling and total open stop-risk budget.
The initial limits remain USD 500 / four supported micro contracts / USD 75 per
trade / USD 150 open risk. Values are stored locally and restored on restart.

**Save safeguards** stores pending settings only. **Review and apply** requires
paused entries, an up-to-date worker, exact-account confirmation and verified
broker-flat state. Higher loss limits require this same explicit approval; no
new values are applied during deployment. Applying never starts trading, resets
the account's loss baseline or unlocks an already latched loss lock. Lowering a
limit below current losses latches it immediately. Any loss-baseline reset remains
a separate explicit authorization in Execution.

Practice and Leader retain separate settings and audit records. Active limits
are checked at the order-send boundary, not only rendered in the interface.
Existing strategy sessions may retain stricter frozen limits until Pause and a
new explicitly authorized Start. Broker/platform restrictions and the supported
one-to-four contract capability are not bypassed. Loss and stop-risk estimates
cannot guarantee fill prices or maximum realized losses.

**Overnight limits** on the same page configure the contract maximum, minimum
post-close cooldown and maximum bid/ask spread in ticks, independently per account.
Existing installations retain their prior defaults: one contract, 15 minutes and
two ticks. Reading older saved records supplies these defaults without rewriting
their saved values or revisions. Changes use the same Save, then explicit paused
and broker-flat Apply workflow. The stricter regular cooldown and account contract
maximum still win; trend, volume, fresh-data and broker-stop checks remain enforced.
The manager applies the overnight cap before arbitration, with the same cap checked
at atomic claim and final preflight. Execution displays the effective size rather
than the larger saved daytime request. Saved strategy/session settings are not
rewritten by this adjustment.

Safeguards validation: 638 regression tests passed, plus production build and
desktop/mobile browser checks for saved/active separation, reload persistence,
explicit higher-limit approval, account isolation and consistent overnight sizing
through manager selection and submission. No real safeguard values
were changed or accounts armed during deployment.

## Strategy Manager

The shared Strategy Manager evaluates all strategies together in shadow/research
mode, with deterministic conflicts, portfolio risk, atomic research reservations,
causal multi-instrument backtests and separate forward paper accounting. Paper is
off by default; these research controls cannot authorize broker orders. Explicit
Practice automation sessions reuse the same decision engine through the existing
executor; Leader manager cutover remains prohibited. Practice and Leader expose the same
catalog and shared parameter/interval controls without copying account execution
permissions. See [Strategy Execution Manager](docs/STRATEGY_EXECUTION_MANAGER.md)
for architecture, validation, file manifest and broker-integration blockers.

## Trade Management

Shared research/paper exit policies add fixed targets, break-even estimates,
monotonic trailing/profit locks, whole-contract partials and MFE/MAE/giveback
diagnostics. Defaults remain off/baseline; existing positions keep their frozen
management and broker amendments are blocked. See
[Trade Management Engine](docs/TRADE_MANAGEMENT_ENGINE.md) and
[Full System Audit](docs/FULL_SYSTEM_AUDIT.md).
