# Local Native Interface

GoXTrade now defaults to a React/TypeScript frontend with a loopback FastAPI server.
Chrome is the display, not the trading engine. There is no Electron installation,
Windows service or automatic Windows startup. Streamlit is retained as a fallback.

## Start, Restart and Stop

Double-click `start_app.cmd`, `GoXTrade.cmd`, or the desktop **GoXTrade** shortcut.
The CMD stays open with these choices:

1. Open or start the interface.
2. Restart only the interface, keeping the CMD and trading workers running.
3. Show interface status.
4. Stop only the interface.
5. Explicitly pause and safely stop trading workers, requiring typed STOP and
   successful existing broker-flat verification. An API outage can block this action.
6. Close the CMD menu, leaving the interface and workers running.

Closing Chrome does not stop the server. Restart verifies the recorded API PID and
does not terminate its process tree. It does not change account Run/Pause choices.
Starting the interface does not start workers, authenticate to ProjectX, arm accounts
or submit orders. Start workers explicitly on Connection when appropriate.

The normal address is http://127.0.0.1:8504. If occupied, ports 8505-8510 are tried;
unrelated port owners are never terminated. The menu prints the selected URL.
Logs are in `data/logs/native_api.out.log` and `native_api.err.log`.
The desktop shortcut points to this checkout's `start_app.cmd`; recreate it with
`powershell -ExecutionPolicy Bypass -File scripts/create_desktop_shortcut.ps1`
after moving the checkout. Keep this checkout while using that shortcut.

Command-line interface control from the project root:

```powershell
.\.venv\Scripts\python.exe -m goxtrade.runtime.native_app start
.\.venv\Scripts\python.exe -m goxtrade.runtime.native_app restart
.\.venv\Scripts\python.exe -m goxtrade.runtime.native_app status
.\.venv\Scripts\python.exe -m goxtrade.runtime.native_app stop
```

## Fresh Checkout Setup

Python 3.13 and Node.js/npm are required for installation and frontend builds.
The launcher prefers `.venv\Scripts\python.exe`, then the existing Python fallback.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Push-Location web
npm.cmd ci
npm.cmd --script-shell=cmd.exe run build
Pop-Location
.\start_app.cmd
```

The launcher rebuilds when frontend sources are newer than the production output;
ordinary use serves the compiled assets without a Vite development server. Build
output, node_modules, the virtual environment, credentials and runtime data are
ignored by Git. Never replace an existing `.env`, account configuration or database
when upgrading. Dependencies are installed in the project virtual environment;
existing worker Python installations are not upgraded by an interface restart.

## Behavior and Safety

Pages use client-side navigation. WebSocket prices are delivered on a 250 ms local cadence;
shared journal snapshots are cached for one second without blocking prices, and chart polling is every
two seconds. Reconnection does not retry financial mutations. Configuration drafts
and chart zoom survive ordinary data updates. Price availability still depends on
the upstream feed and independently running market worker.

The API reuses existing broker preflight, strategy, account replacement, loss-lock,
protective-order and reconciliation services. Saving controls never arms an account.
Arming requires explicit safeguards and the exact account name, plus a fresh worker
snapshot for that identity. Existing account authorization and risk restrictions
remain. No order or account authorization was performed to validate this interface.

Credentials remain backend-only. Existing keys are never returned. Saving new
credentials requires idle profiles and stopped trading workers. Account refresh,
login tests, historical backfill and research runs are explicit operator actions;
opening a page does not contact the broker.

The server binds only to loopback. Host and Origin checks, bounded same-origin
sessions, HttpOnly/SameSite cookies, CSRF tokens and WebSocket checks guard browser
access. This is a trusted local-computer app, not an Internet-authenticated service.
Do not expose it through a tunnel or bind it to a public network without a separate
security review. An administrator or malicious local program is outside this boundary.

Journal reads are bounded to 10,000 jobs and 50,000 fills per snapshot; response
lists are additionally bounded. Very large archives need paginated reporting before
their complete lifetime totals can be claimed. Research keeps historical, forward
paper, Practice and Leader results separate. The native CSV form uses actual minute
OHLCV and explicit cost assumptions, not invented intrabar ticks. Advanced legacy
research remains available in Streamlit (`app.py`, port 8502) when explicitly started.

ProjectX availability is unresolved. Authentication, account replacement and actual
broker integration were not verified against the unavailable provider. No measured
trading latency or real-market profitability is claimed.

## Validation

`python -m unittest discover` passed 455 tests with no failures, errors or skips.
These include local API access controls, sanitized errors, arm preconditions,
no-startup-side-effects and interface-only restart tests. Broker responses are mocked.
TypeScript checking and the production build passed. The initial JavaScript bundle
is approximately 91 KB gzip; the chart library is loaded separately.

`python -m tests.test_native_browser` checks desktop/mobile navigation, no overflow,
WebSocket updates, chart rendering, persistent zoom, resizable indicators and the
authorization dialog without confirming execution. Set `GOX_TEST_NATIVE_RESTART=1`
to include an interface-only restart and reconnection check. Chart fixtures are
intercepted only in the test browser, never stored as market data. Screenshots stay
under ignored `data/verification/`.

`python -m tests.test_native_controls_browser` routes browser requests through the
real local API with a disposable SQLite database and all broker actions blocked.
It verifies both profiles, every eligible strategy on/off and all-off, MYM, contract
sizes and bounds, cooldown, intervals and VWAP parameters after full reloads. It also
checks stale runtime snapshots, reconnects during editing, independent unsaved tabs
and rejected saves. Production settings are never changed by this test.

Control Center edits are drafts until their tab's Save button succeeds. The form
shows unsaved changes and confirmation separately. Configuration reads include saved
execution settings directly instead of using the cached live runtime as form defaults.
Saving configuration does not change Run/Pause, reset loss limits or modify open trades.

The Trade Management sidebar page shares research exit policies in both account
views, without modifying account execution settings. Its four tabs show separately
labeled broker snapshots, paper protection, giveback diagnostics and ten-policy
comparisons. `python -m tests.test_trade_management_browser` checks both views at
six viewport sizes, populated fixture tables, persistence and failed-save drafts
against a temporary database with broker transport blocked. Existing Strategy
Manager/Control Center browser checks also pass at six sizes.
