# Workspace and Account Maintenance

The October 2026 redesign uses the GoXFinance reference's charcoal background
`#151716`, sidebar `#101211`, sage accent `#adbcad`, neutral typography and the
same Inter/system font stack. No fonts, credentials or account data were imported
from GoXFinance. It was inspected read-only as a design reference.

## Workspaces

The default interface is now React/TypeScript with a local FastAPI server. Start it
with the desktop shortcut or either CMD launcher; use menu option 2 to restart the
interface without stopping trading. See [NATIVE_APP.md](NATIVE_APP.md). The legacy
Streamlit entry point remains available but is no longer the default launcher.

| Page | Purpose |
|---|---|
| Dashboard | Broker-matched closed-trade statistics; current account versus archived identities; research stays separate |
| Charts | Up to three real-price charts, range/candle interval/height, volume, RSI and persistent zoom |
| Strategies | Live strategy matrix, prioritized actual trades, setup/exit evidence, alert history and research |
| Control Center | Practice/Leader strategy permissions, 1-4 micro quantities, MYM activation and 1-60 minute post-close delay |
| Execution | Explicit authorization, Run/Pause, protection, emergency-close requests and actual fills |
| Accounts | Explicit read-only account refresh and safe replacement of execution identities |
| Connection | Locally stored API key, login test, market worker, safe maintenance stop and instrument mappings |
| Research | Source-separated saved runs and explicit actual-minute-CSV backtests |

Legacy `?page=Market`, `Bot` and `Live` links remain supported. Ordinary navigation
does not own the worker lifetime. Saving configuration never arms execution.
Existing 15-minute strategy signal definitions remain intact; stop management
supports 5/10/15-minute candles, ORB ranges support 5/15/30 minutes, and the new
VWAP strategy retains its independent interval configuration. Overnight cooldown
and size restrictions can be stricter than the requested Control Center values.
Existing open positions retain frozen management; new settings affect new setups.

## Credentials and API Availability

Enter username and API key on Connection. The password field never displays an
existing key. Saving uses dotenv quoting and retains unrelated `.env` settings.
The form clears after submission. Credentials and local settings remain ignored by
Git. Pause and stop workers before changing an active login; restart workers after
changing credentials. Connection testing is explicit and does not submit an order.

The user reports ProjectX API access is currently unavailable. No actual API repair,
successful authentication, account retrieval or live execution is claimed by this
redesign. Offline previews show unavailable/empty data rather than fabricated fills.
Resolve provider access before attempting account verification or execution. Send
support the endpoint/error/status and timestamp, never the API key or bearer token.

## Replacing a Reset or Failed Account

1. Pause both Practice and Leader. Resolve all open/pending/uncertain jobs.
2. On Connection, use **Pause & stop trading workers**. Broker-flat verification
   must succeed; an API outage blocks shutdown rather than abandoning protection.
   The web UI remains open for maintenance.
3. Refresh the enabled account directory on Accounts. Enter the numeric broker
   account ID and exact new name under Replace execution account.
4. Confirm the role/copier setup and flat/stopped state. Verification re-fetches
   accounts and checks both old/new positions and working orders; cached account
   lists are never sufficient evidence.
5. Save the replacement, then restart the full app and workers. Only after restart
   may the new identity be explicitly authorized on Execution.

Supported replacement targets are isolated `PRAC-` simulated accounts and simulated
`50KTC-` Trading Combine leaders. This does not enable funded-account trading or
configure Topstep followers. If an old failed account is inaccessible, replacement
remains blocked until its exposure can be verified or handled in a separate reviewed
recovery procedure. Do not erase its orders/history to bypass the guard.

Overrides are stored in ignored `data/execution_accounts.json`. Existing local
Python configuration remains fallback only. New worker processes freeze the validated
target at startup. Stale UI/worker processes cannot arm, claim or submit entries
after their account identity changes. Missing legacy configuration permits offline
setup with non-trading placeholder identities; malformed overrides fail closed.

The account registry retains each identity's loss-lock key. Re-selecting an earlier
account reuses its original loss lock; replacing the same account is rejected as
a reset mechanism. Old fills/jobs/loss approvals remain stored. A replacement clears
only the profile's stale starting-balance reference and leaves it paused; it never
acknowledges or deletes a loss lock. Defaults for a new identity are not permission
to trade. Sizing remains in Control Center. New fills with known account IDs are
not mixed with another account's P&L. Legacy records without identity retain their
old compatibility behavior and cannot establish independently verified attribution.

## Validation

The final `python -m unittest discover` run passed **280 tests**, zero failures,
errors or skips (42.123 seconds). Compilation also passed. New tests cover
read-only replacement, account mismatch/funded/disabled refusal, open/uncertain
exposure, restart enforcement, loss-lock/history preservation, cross-account P&L,
safe worker-only shutdown, explicit account refresh, credential preservation and
Control Center saving without arming. All broker responses are mocked.

`python -m tests.test_workspace_browser` verifies all seven pages at desktop/mobile
sizes without horizontal overflow or page errors. `python -m tests.test_vwap_ema_browser`
verifies chart pixels, indicators, markers, levels and persistent zoom. Neither
presses execution controls. Browser screenshots remain ignored under `data/verification`.
Provider-side API access and actual account replacement remain unverified while
the API is unavailable. The $500 lock, protective-order requirements, no-hedging,
volatility/session gates and VWAP Leader prohibition are unchanged.
