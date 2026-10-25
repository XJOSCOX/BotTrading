# GoXTrade

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
structure confirmation. Monitoring defaults on; forward paper and broker Practice
default off. Leader execution is prohibited. See
[PREVIOUS_DAY_BOX.md](docs/PREVIOUS_DAY_BOX.md) for session/calendar requirements,
chart/settings/research integration, safeguards, validation and deployment limits.
Strategy watch always lists registered strategies, even without worker results.

## Phase 2 Validation

See [PHASE2_VALIDATION.md](docs/PHASE2_VALIDATION.md) for confirmed defects, regression
coverage, calendar configuration and remaining deployment blockers. Research now
requires an explicit commission or acknowledged zero-cost sensitivity scenario.
VWAP broker Practice additionally requires a fresh operator-reviewed CME calendar;
missing calendar information blocks this strategy, never grants permission.
No real-market profitability or TradingView feed parity has been established.

## VWAP EMA Cross

The new strategy defaults to completed **3-minute** candles, **EMA9 Close**, and
**OHLC4 session VWAP weighted by actual traded volume**, anchored at 17:00 Chicago.
Existing five strategies retain their 15-minute signal rules. The strategy registry
declares independent timeframes, data requirements, canonical IDs and execution eligibility.

Open **Bot > VWAP EMA Cross** for status/chart, validated Parameters, historical
Backtest and source-separated Comparison. Monitoring defaults on; forward-paper and
broker Practice default off. Saving settings never arms an account. **Leader execution
is prohibited for this strategy**, including REALTIME and experimental ANTICIPATORY modes.

Historical research accepts actual timezone-aware minute OHLCV CSV or saved
contract-specific data. Intrabar modes additionally require ordered actual trade
observations; no intrabar signals are invented from OHLC. Comparisons keep historical,
forward-paper, broker Practice and Leader P&L separate. No verified profitability is
claimed. Read [VWAP_EMA_CROSS.md](docs/VWAP_EMA_CROSS.md) for formulas, enabling Practice,
data coverage, risk snapshots, schema additions, fill assumptions and known limitations.

Run offline unit tests with `python -m unittest discover`. Browser checks live in `tests/` and require a local app and Playwright with Edge; run them as modules, such as `python -m tests.test_leader_browser`. They do not submit orders. `python -m scripts.practice_smoke_test` places broker orders; review it before use.

## Strategy Manager

The shared Strategy Manager evaluates all strategies together in shadow/research
mode, with deterministic conflicts, portfolio risk, atomic research reservations,
causal multi-instrument backtests and separate forward paper accounting. Paper is
off by default; broker cutover is prohibited. Practice and Leader expose the same
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
