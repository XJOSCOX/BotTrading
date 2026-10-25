# GoXTrade

A Streamlit trading workspace with market charts, strategy alerts, account statistics, and opt-in Topstep execution.

## Local Configuration

Install dependencies with `python -m pip install -r requirements.txt`.
For a new checkout, copy `.env.example` to `.env` and `goxtrade/config/execution_target.example.py` to `goxtrade/config/execution_target.py`. Configure credentials and exact account identities locally before execution. The example identities are placeholders, not trading accounts. Optional copy-role labels use `goxtrade/config/copy_accounts.json` with `leader` and `followers` account names; these labels do not configure or verify broker copying.

When updating an older installation, move its existing `execution_target.py` and optional `copy_accounts.json` from the project root into `goxtrade/config/`. Preserve the existing `.env` and `data/` folder in the project root.

Credentials, account configuration, databases, logs, and trading history are excluded from Git. Do not overwrite existing local configuration when updating an installation.

## Run

On Windows, double-click `start_app.cmd` to start or repair the local app processes.
This does not require Chrome to stay open. Use `GoXTrade.cmd` for the Start/Stop menu;
Stop pauses new entries and requires verified flat broker accounts before processes
are shut down. Neither launcher automatically enables a paused trading profile.

To run Streamlit directly during development:

```powershell
C:\Python313\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

## Project layout

```text
app.py                  Streamlit entry point
start_app.cmd           Start or repair the app
GoXTrade.cmd             Start/Stop menu
goxtrade/
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

Run commands from the project root. Background workers and diagnostics use package imports; for example, `python -m scripts.check_executor_idle`. Use `python -m goxtrade.runtime.manage_app start` or `stop` for command-line process control.

## Current Scope

- Dashboard: executed-trade statistics and connection settings.
- Market: live candlesticks, volume, RSI, and multi-chart views.
- Bot: CRT, Reversal, ORB, VWAP Reclaim, EMA Pullback, and VWAP EMA Cross monitoring.
- Live: separately controlled Practice and Leader execution, micro sizing, reconciliation, and account loss locks.

See [BOT_OPERATIONS.md](docs/BOT_OPERATIONS.md) for strategy rules, safeguards, and limitations. New setups support 5/10/15-minute stop management. Automated trading can lose money; test in Practice before enabling a Leader account.

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
