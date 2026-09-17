# GoXTrade

A Streamlit trading workspace with market charts, strategy alerts, account statistics, and opt-in Topstep execution.

## Local Configuration

Install dependencies with `python -m pip install -r requirements.txt`.
For a new checkout, copy `.env.example` to `.env` and `execution_target.example.py` to `execution_target.py`. Configure credentials and exact account identities locally before execution. The example identities are placeholders, not trading accounts. Optional copy-role labels use `copy_accounts.json` with `leader` and `followers` account names; these labels do not configure or verify broker copying.

Credentials, account configuration, databases, logs, and trading history are excluded from Git. Do not overwrite existing local configuration when updating an installation.

## Run

```powershell
C:\Python313\python.exe -m streamlit run app.py --server.port 8502
```

## Current Scope

- Dashboard: executed-trade statistics and connection settings.
- Market: live candlesticks, volume, RSI, and multi-chart views.
- Bot: CRT, Reversal, ORB, VWAP Reclaim, and EMA Pullback monitoring.
- Live: separately controlled Practice and Leader execution, micro sizing, reconciliation, and account loss locks.

See [BOT_OPERATIONS.md](BOT_OPERATIONS.md) for strategy rules, safeguards, and limitations. New setups support 5/10/15-minute stop management. Automated trading can lose money; test in Practice before enabling a Leader account.

Run offline unit tests with `python -m unittest discover`. Browser checks require a local app and Playwright with Edge; they do not submit orders. Do not run smoke-test scripts against an account without reviewing their order-placement behavior.
