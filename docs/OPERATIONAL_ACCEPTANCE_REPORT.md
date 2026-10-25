# Phase 8: Operational Acceptance Report

## 1. Revision And Scope

Observed October 25, 2026, America/Chicago; local evidence captured at 11:23 CT.
Starting revision: `7aece035968ce1e17e1c3870ad1cea55ab6e1ec5` on
`origin/feature/system-hardening`. A fresh fetch confirmed `7abad6f` and `7aece03`
with no subsequent remote changes. The worktree was clean. Work is delivered on
`feature/operational-acceptance`; no automatic merge into `main`.

The existing diagnostics, research store, seven strategies, replay/backtest kernel,
arbitration, risk and management engines were reused. No entry strategy or trading
parameter was introduced or optimized. No credential, account assignment, funded
account risk setting, copier setting, production history or persistent safety lock
was changed. No real authentication request, order, arming or trading-worker
restart was performed.

**Overall conclusion: software acceptance progressed; real-market validation is
BLOCKED.** Passing fixtures must not promote broker readiness.

## 2. ProjectX Configuration

| Check | Actual local evidence | Classification |
|---|---|---|
| API endpoint | Approved HTTPS `api.topstepx.com` configuration | VERIFIED configuration only |
| Market-data endpoint | Approved HTTPS `rtc.topstepx.com` configuration | VERIFIED configuration only |
| Username / API key presence | Both absent in this checkout's configured environment | BLOCKED |
| Account configuration | Current identities resolve to example/placeholders, not configured execution accounts | BLOCKED |
| Instrument mappings | Six local mappings present: MNQ, MES, MYM, NQ, ES, YM | PARTIALLY VERIFIED; provider identities/active status not checked |
| Required subscription / entitlement | Not established from provider evidence | NOT TESTED |
| Live feed | Collector telemetry unavailable; no local quote/trade observations | NOT TESTED |
| Exchange session | Modeled exchange closed at inspection; entry window closed | VERIFIED local calendar calculation, not a provider-health claim |

The initial diagnostic incorrectly called placeholders configured. After repair,
both profiles correctly show unconfigured. No account was removed or reassigned.
Sensitive account names/IDs and credential values are deliberately absent here.

## 3. Authentication Outcome

**NOT TESTED: missing local credentials. Zero real authentication requests.**
No secrets were requested and no alternate credential location was searched.
The specified conditional single bounded probe was therefore not sent. Existing
mock tests exercise success, rejected credentials, permission rejection, HTTP 429,
timeouts, provider errors, malformed responses and unknown codes. These are
software classifications, not actual ProjectX outcomes.

The explicit read-only Diagnostic Center remains the correct future probe path.
It allowlists login, contract-by-ID and bars; diagnostics never submit orders or
restart workers. Rejected authentication is not automatically retried. Blank
tokens are now malformed, and a failed missing-credential preflight clears any
prior diagnostic token rather than retaining a misleading success state.

## 4. Historical Retrieval Outcome

**NOT TESTED: authentication unavailable. Zero real contract/history requests.**
No empty provider response was received, so there is no evidence of provider
outage, expired-contract retention, subscription failure or missing provider data.
The modeled exchange closure is separate from all those questions.

A future history probe must verify the exact contract and tick specifications via
the existing read-only contract lookup, then request a small finalized past MNQ
or MES interval. Do not infer active contract/expiration from default mappings.

## 5. Genuine Dataset Quality

**BLOCKED - VERIFIED DATA UNAVAILABLE.** Read-only local inspection found:

| Store | Rows |
|---|---:|
| Canonical historical minutes | 0 |
| Locally aggregated trade minutes | 0 |
| Captured live events | 0 |
| Validation Lab datasets / runs | 0 / 0 |
| Replay sessions / recorded tick packs | 0 / 0 |

There was no existing genuine dataset whose contract, timestamps, traded volume,
provenance, calendar coverage and integrity could be validated. No synthetic data
was imported into production or substituted for real historical validation.
All software fixtures remained in temporary directories/databases.

Hash comparison during the local evidence inspection found the production DB,
local credentials and account/copy configuration files unchanged, including files
that were absent. This is a bounded inspection check, not a power-loss or
concurrent-worker guarantee.

## 6. Replay Acceptance

Real-data signal counts, fills, P&L and a real-data complete decision export are
**NOT TESTED**. There is no market replay result to export.

Offline fixture acceptance passed through the existing shared engine:

- Play, pause, resume, step, stop, restart and validated playback speeds.
- All six speed settings produce identical candle-step state/decisions.
  Maximum-speed playback parity remains covered separately.
- A simulated open position survives stop, cache loss/restore and resume; its
  eventual episode is booked once. Stop does not invent a liquidation.
- Cold restart creates an empty, paused, separate virtual session and preserves
  the old session. Restored source/code/revision mismatches fail closed.
- Replay/backtest equality, persisted recorded-tick observation state,
  no-lookahead, stale/gap/rollover rejection and no-account-write tests pass.
- All ten existing exit-policy configurations retain incremental/batch parity.
- The 10,000-candle no-participating-strategy benchmark has exact final-state
  parity between batch and 100 checkpoint batches.

These are shared-kernel consistency checks, not an independent implementation or
real market validation. Minute OHLC cannot establish intrabar order: old-stop-first
ambiguity, next-observation entries and next-bar new trails are intentional.
Recorded ticks require actual ordered observations and can legitimately produce
different fills/excursions. No synthetic historical tick path was generated.

## 7. Strategy Acceptance Matrix

All seven are registered, selectable and exercised by their existing offline
suites. **Actual data/indicator readiness and genuine signal generation are
BLOCKED for every strategy in this environment.** A missing dataset is not zero
valid signals. No strategy was silently dropped to obtain a successful result.

| Strategy | Required indicators/history | Confirmation / expiration | Missing-data behavior and market limitation |
|---|---|---|---|
| CRT | Completed 15-minute range and sweep candles | Original 1m/5m revalidation; legacy window caveat below | Wait/reject incomplete candles, invalidation or stale price; genuine setups not evaluated |
| RSI Reversal | RSI14 on completed registered 15-minute candles with initialized history | Completed reversal and original multi-timeframe confirmation; legacy window | Wait for initialization; no fabricated RSI or signal |
| ORB | Actual 08:30 CT opening minutes, selected 5/15/30-minute range, completed registered breakout candles | Two completed breakout closes plus original revalidation; legacy window | Missing opening range and outside cash-session entries rejected |
| VWAP Reclaim | Actual traded volume and complete session from 17:00 CT; VWAP, EMA20/50 | Completed retest/reclaim/rejection with trend agreement; legacy window | Missing anchor coverage, volume or trend initialization means ineligible |
| EMA Pullback | Contiguous registered candles; EMA20/50, RSI14, ATR/retest context | Completed momentum and RSI50 recovery; original revalidation; legacy window | Wait on warmup/gaps; no bridged missing candles |
| VWAP EMA Cross | Configured interval, 3-minute default; anchored VWAP/EMA9, sufficient complete-session warmup | Frozen original event revalidated; 90-second default configurable expiry | Incomplete session/volume prevents eligibility; REALTIME/ANTICIPATORY require actual recorded ticks, not minute fabrication |
| Previous Day Box Reversal | Complete previous actual-contract session and completed 15-minute confirmation | Original frozen box/rejection/structure envelope; 90-second default configurable expiry | Missing previous session, expired/wrong contract or invalid box blocks eligibility |

Common software checks passed: explicit identity, indicator initialization tests,
entry confirmation, expiry, instrument tick/point values, structural stop geometry,
costed portfolio risk, replay compatibility, stale quotes and history gaps.
Actual execution eligibility is not established by registration or passing tests.

### Existing Practice/Leader Window Difference

`entry_confirmation.window_open` still grants legacy 15-minute setups a
600-second post-close window in Practice/research but 300 seconds in Leader.
Price-drift handling also differs: Practice/research can wait where Leader cancels.
This is an existing behavioral difference, not full Practice/Leader parity.
An explicit regression documents the expiration difference. The conservative
Leader behavior was retained rather than silently widening live entry eligibility
without market validation. Resolve the intended policy before claiming parity.

## 8. Profit Protection

No genuine historical profit comparison was run. No policy ranking, profitability
claim or strategy confidence score is justified by this milestone.

Existing correctness suites compare baseline, fixed 1R/1.5R/2R, break-even,
ATR/structure trailing, profit lock, partial-plus-trailing and hybrid policies.
They verify MFE/MAE, maximum/current/captured R, quantity conservation, fees/net
accounting, capture/giveback, duration, reasons, monotonic stops and causal bars.
The Phase 7 100-scenario reversal grid is rerun in the full suite and exercises
+0.5/1/1.5/2/3R peaks in both directions. Its baseline is the frozen fixture
baseline; separate integration tests exercise `structure-v1` adaptive management.
It is not a 100-trade real adaptive-policy performance sample.

Fixture tests explicitly flag episodes reaching +1R/+2R then closing negative.
Those labels are correctness evidence, not evidence that faster exits improve
expected returns. Software stops can gap; an observed favorable price does not
promise a broker fill. Broker-side dynamic amendments/partial exits remain blocked.

## 9. Portfolio Risk

**VERIFIED within deterministic/mock scope:** immutable candidate identity,
same/opposing-signal arbitration, expiry, consumed setup deduplication, explicit
costs, sizing within structural risk, account/daily/open/correlation limits,
existing exposure, stale/unresolved state, cooldown and restored-state validation.
These tests do not establish actual broker balances, realized loss, slippage or
fresh risk state in this checkout.

## 10. Practice Safety

**BLOCKED for broker execution.** Exact Practice identity, explicit arming,
independent strategy permissions, $500 cumulative loss lock, reconciliation,
ownership, protective stops, unknown outcomes, emergency and duplicate-intent
barriers pass mocked tests. Local account configuration is placeholder-only and
no fresh broker snapshot exists. No Practice test order was placed.

## 11. Leader Safety

**BLOCKED for broker execution.** Separate Leader authorization and account/loss
locks, direct command isolation, unresolved-state blocking and protective-order
checks pass mocked tests. There is no provider or copier verification. Neither
selecting strategies nor passing Practice fixtures arms the Leader. The research
manager is still not cut over to broker submissions; actual workers retain their
existing execution path.

## 12. Operational Recovery

| Scenario | Actual evidence / limits |
|---|---|
| No-position restart | New replay starts empty/paused; actual isolated local API process lifecycle also tested |
| Simulated open-position interruption | Explicit stop/restore/resume preserves state and creates one completed episode |
| Interrupted historical download | Existing temporary-store chunk/cursor, retry/resume, cancellation and owner-fence tests pass; no real download attempted |
| Temporarily unavailable DB | New passive reader reports UNAVAILABLE, not zero/healthy; recovers when fixture lock releases; Phase 7 replay failure latch tests pass |
| Invalid response / timeout / rejected auth | Mocked classification, sanitization, bounded retry and durable unknown-outcome tests pass |
| Stale data / gap / mismatch / expiry | Existing data, confirmation, calendar and contract suites fail closed |
| Unknown order / loss lock / missing stop | Mocked executor and reservation tests preserve locks/intents and block new orders |
| Exchange closure | Local closure remains separate from feed/API status; no outage inferred from absent events |
| Real broker crash/recovery | NOT TESTED; no real position, API session or broker worker was restarted |
| Disk corruption / power loss | NOT TESTED; no production repair, deletion or automatic lock reset attempted |

The standalone lifecycle harness creates only its own test API children, with
provider POSTs forbidden and an absent temporary account DB. Three starts,
60 read-only diagnostic requests and three forced child terminations succeeded.
The test asserts the missing account DB remains missing. This is **not graceful
broker shutdown/drain validation**. An initial harness assertion wrongly expected
READABLE; it was corrected to verify the intended MISSING/no-creation behavior.

## 13. Performance And Stability

All measurements below are synthetic/local software workloads. They are neither
market data nor broker/exchange-to-browser latency. Phase 7 comparison values come
from its published report. Concurrent host load and code/source checks differ;
no controlled speedup or regression attribution is claimed. No algorithmic
performance optimization was applied.

| Existing benchmark | Phase 7 | Phase 8 |
|---|---:|---:|
| 3-candidate arbitration median / p95, 100 runs | 0.211 / 0.403 ms | 0.216 / 0.263 ms |
| Seven adapters median / p95, 30 runs | 56.907 / 59.837 ms | 59.823 / 62.772 ms |
| 180-candle seven-strategy pass, tracemalloc enabled | 27.843 s wall | 38.954 s wall / 38.516 s CPU |
| Peak Python-traced allocations (not RSS) | 6.745 MB | 6.744 MB |
| 10,000-candle no-strategy kernel: batch / checkpoint batches | 43.049 / 44.149 s | 48.137 / 49.017 s |
| Kernel preparation | 0.078 s | 0.085 s |
| SQLite read during writer median / p95 | 0.350 / 0.951 ms | 1.310 / 2.441 ms |
| SQLite write with reader median / p95 | 4.159 / 26.159 ms | 2.999 / 19.385 ms |
| Cached empty API snapshot median / p95 | 2.599 / 3.214 ms | 3.148 / 3.807 ms |
| 20 replay play/pause cycles median / p95 | 238.348 / 271.207 ms | 259.350 / 269.415 ms |

New measured operational checks:

- Three isolated API startups: 1,126-1,143 ms. Forced child teardown: 1.00-1.04 ms.
- 60 actual loopback diagnostic requests: median 2.862 ms, p95 203.857 ms,
  including cold/lazy initialization; empty missing account/research stores.
- Six viewports: navigation to first nonblank fixture chart 379-530 ms, including
  client navigation, fixture response and lazy chart loading. The final repeat
  measured 379-543 ms. Neither run measures actual price lag.
- Eight native pages at six sizes: navigation median 30.735 ms, range
  17.18-371.88 ms, including mobile drawer interactions.
- Four malformed stream cases: recovery 1,067-1,080 ms; one document load,
  no uncaught browser error. Local interface recovery is not provider recovery.

Research/read-only inspections are bounded by row counts and SQLite read budgets.
Missing, locked, malformed or newer-schema stores do not trigger migrations,
account mutations or fabricated zero balances. Long research work still has no
hard real-time CPU isolation guarantee.

Reproduce with `python -m tests.benchmark_system_hardening`,
`python -m tests.benchmark_offline_replay` and
`python -m tests.benchmark_operational_startup`. These are explicitly labeled
fixture/local lifecycle tests, not market performance tests.

## 14. Tests Executed

| Command / suite | Outcome |
|---|---|
| Baseline `python -m unittest discover` | 504 passed, 97.188 s |
| Final `python -m unittest discover` | **515 passed, 122.376 s; 0 failures, 0 errors, 0 skips** |
| `python -m compileall -q goxtrade scripts tests` | Passed, including final test harnesses |
| TypeScript + `npm.cmd --script-shell=cmd.exe run build` | Passed; entry JS 97.89 KB gzip; separate chart library retained |
| Operational acceptance browser | Six sizes; seven registered strategies, two profiles, six injected refresh failures recovered, chart pixels checked; zero provider requests/account writes |
| Native hardening browser | Eight pages x six sizes, nonblank charts, four stream-failure recoveries, no JS errors/account writes |
| Offline Replay / Diagnostics browser | Six sizes, controls/pixels, sanitized **mocked** auth probe, no real provider calls |
| Validation Lab browser | Six sizes, both profiles, all strategies/research tabs, temporary fixtures only |
| Existing benchmarks | Kernel parity plus arbitration/adapters, allocations, contention, API and 20 replay cycles completed |
| Isolated local API lifecycle benchmark | Three starts/stops and 60 GET probes passed; no existing app or account worker touched |

Eleven additional unit-test methods cover operational bugs, passive read-only
evidence/privacy, DB failure, replay recovery/speed and the documented legacy window
difference. Four diagnostic regressions were reproduced failing before repair.
Refresh error handling and table readability have browser regressions. Existing
non-failing Starlette/httpx, legacy Streamlit and pandas warnings remain; dependency
upgrades were not mixed into operational acceptance.

## 15. Confirmed Fixes And Files

1. Placeholder identities no longer count as configured execution accounts.
2. A missing-credential authentication preflight clears an old diagnostic token.
3. Whitespace-only diagnostic tokens are malformed, never authentication success.
4. Future-dated market events are invalid evidence, never fresh age-zero quotes.
5. Manual diagnostic refresh failures are caught; successful retry/poll clears the
   stale error instead of leaving misleading failure text or an uncaught rejection.
6. Narrow operational table cells retain whole status words and profile names.

The existing Diagnostics page now includes passive operational evidence: all
registered strategies, recent/stale monitor state, quote freshness **separate from
unverified history**, recorded rejection reasons, saved research/replay metadata,
both profiles' selected strategies/additional opt-ins, saved loss locks, recent
broker snapshot availability, unresolved/ambiguous jobs and explicit unverified
protection. No arbitrary status is promoted to healthy by opening this page.
Manager rejection evidence is labeled research/shadow, not a broker rejection.
Stored metadata eligibility is not independent source integrity or market proof.
Private configured identities/credential values are removed from rejection text.

Files:

- `goxtrade/diagnostics/projectx_diagnostics.py`
- `goxtrade/diagnostics/operational_evidence.py`
- `web/src/pages/Diagnostics.tsx`
- `web/src/styles.css` (scoped operational table rules only)
- `tests/test_operational_acceptance.py`
- `tests/test_operational_acceptance_browser.py`
- `tests/benchmark_operational_startup.py`
- `docs/OPERATIONAL_ACCEPTANCE_REPORT.md`
- `README.md`

Generated screenshots/JSON/logs remain ignored under `data/verification/`; no
fixture dataset or account payload is committed. Commands and measured results
above are retained here so readiness does not depend on those local files.

## 16. Remaining Blockers And Readiness

| Category | Classification | Conclusion |
|---|---|---|
| Offline research software | VERIFIED within fixture scope | Deterministic correctness, isolation, causal replay, arithmetic and UI tests pass |
| Real historical backtesting | BLOCKED | No credentials, provider retrieval or genuine verified dataset |
| Forward paper | PARTIALLY VERIFIED software; currently data-blocked | Kernel/restart correctness passes; sustained genuine fresh-feed operation untested |
| Broker Practice | BLOCKED | Placeholder identity, no real access/protection/recovery verification, no current account snapshot |
| Broker Leader | BLOCKED | Same gates plus independent exact-account/copier authorization; legacy window difference unresolved |

Additional unverified areas: actual subscription/history retention, active and
expired contract metadata, operator-reviewed current calendar, sustained latency
under market volume, real costs/slippage, provider outages, partial fills and
unknown outcomes across actual process/power loss. Broker profit amendments and
partial exits remain disabled. No profitability conclusion is available.

## 17. Recommended Operator Actions

1. After reviewing/updating the branch, use the manual launcher's interface-only
   restart to load it; existing account workers were not upgraded/restarted here.
   Configure credentials and exact accounts privately through the existing
   Connection/Accounts workflow; do not paste secrets into chat. Configuration
   alone must not arm either profile.
2. Run one explicit Diagnostic Center authentication probe. If rejected, stop and
   resolve the reported credential/permission issue; do not repeatedly retry.
3. After successful auth, validate a real MNQ/MES contract and small finalized
   historical interval. Confirm source, volume, gaps, timezone and response quality.
4. Save a genuine Lab dataset with verified expiration/calendar provenance. Expand
   warmup to the prior session where required, keeping each ineligible strategy's
   actual reason visible. Do not invent coverage to produce trades.
5. Replay stepwise and compare frozen-cost/risk configurations with backtesting and
   all exit policies. Review decisions and excursions rather than cherry-picking
   profits. Then supervise forward-paper on verified fresh data.
6. Resolve the intended Practice/Leader legacy entry-window/drift policy before
   claiming identical execution behavior. Any later broker acceptance must be a
   separately authorized milestone with independently validated protection and
   recovery semantics. Do not auto-enable Leader.

New commit hashes and the pushed feature branch are supplied in the delivery
response. `main` remains unmerged. No account activation is part of Phase 8.
