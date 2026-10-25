# Pre-Deployment Audit: Phase 7

Date: 2026-10-25. Audited base: `99f1b3a` on
`origin/feature/offline-replay-diagnostics`. Delivery branch:
`feature/system-hardening`. No automatic merge, account activation, provider
authentication, order, copier change, account reset or trading-worker restart.

## Conclusion

**Suitable for controlled offline research and supervised forward-paper testing,
not certified for Practice or Leader deployment.** Deterministic fixtures are not
real-market results. Real provider access, protective-order semantics, current
calendar review and broker recovery still require independent verification.

The existing account workers remain distinct from the research execution manager.
Passing manager simulations does not demonstrate that the legacy broker executor
uses manager arbitration or its experimental profit policies. Broker manager
cutover, profit amendments and partial-exit transport remain prohibited.

## Inspection Scope

`python -m scripts.audit_system` reads the tracked/unignored application sources,
configuration, tests, frontend, launchers and documentation; parses Python ASTs
and JSON; and maps direct-import test references. The dependency lock is read
separately. Ignored credentials, account files, databases, logs and vendor/build
outputs are excluded. The starting inventory contained 305 files / 34,532 lines.
The final reproducible inventory contains 310 enumerated files, including this
milestone's additional tests/docs.

That inventory is **not** proof of semantic correctness, complete independent
manual review, or line/branch coverage. The script distinguishes current targeted
semantic review from prior-milestone reviews and static-only inspection. Current
review concentrated on account identity, executor send/close boundaries,
reconciliation, reservations, risk, management/accounting, historical/forward-paper
kernels, replay persistence/playback, diagnostics, API error boundaries and live
frontend updates. Existing strategy-specific suites were rerun for all seven
strategies; no strategy rule or profit parameter was optimized.

The explicit order script `scripts/practice_smoke_test.py` was inspected statically
but **not run**. No test intentionally calls a real broker transport.

## Confirmed Defects And Fixes

| ID | Reproduced problem | Repair / regression evidence |
|---|---|---|
| F1 | Login accepted truthy non-boolean success and invalid token types; malformed JSON/non-object responses escaped as raw parser/attribute errors. | Strict object/boolean envelope and nonblank string token; sanitized `ProjectXResponseError`. Submission outcomes remain unknown, never blindly retried. |
| F2 | Executor/history callers could repeatedly authenticate unchanged, explicitly rejected credentials. | Process-local, synchronized fingerprint latch for documented authentication/permission rejection only. Changed credentials can retry; unknown/transient errors are not falsely classified as permanent. |
| F3 | Exposure responses were not checked as collections or for conflicting account IDs. | Reject malformed position/order collections and explicit foreign-account rows; never interpret them as flat. |
| F4 | Parent-linked stop orders with absent, nonfinite, nonpositive or off-grid stop prices counted as protection. | Shared executor protection predicate validates price/grid and explicit account identity; reconciliation and additional-entry checks use it. Profit-side tightened stops remain valid. |
| F5 | Restored truthy strings could stand in for verified safety switches. | Manager eligibility requires actual booleans for session, pause, arming, reconciliation, uncertainty, emergency and loss-lock state. |
| F6 | Restored exposure could label a known MNQ ProjectX contract as MES and pass risk checks. | Exposure validation checks known ProjectX contract/product consistency before calculating capacity. Other providers' arbitrary IDs still require caller provenance verification. |
| F7 | Thread-start failure left playback saved as playing; database failures could throw again inside the replay failure handler. | Sanitized startup failure, generation-fenced pause, in-process pending pause when storage is unavailable, recovery before subsequent controls/inspection. A stale failure cannot overwrite a newer controller. |
| F8 | Replay chart EMA warmup reset at the 500-bar display boundary. | Compute indicators on all causally revealed, bounded history before truncating the display. Regression checks the 520-bar case. |
| F9 | Invalid HTTP Content-Length caused a 503 or accepted negative lengths. | Validate the header and return a sanitized 400; oversized valid lengths retain the 413 boundary. |
| F10 | Malformed WebSocket frames threw uncaught frontend exceptions while the UI could remain connected. | Validate frames, mark disconnected and reconnect with a sanitized error; no document reload or account mutation. |

Most injected regressions were observed failing before their repairs. The restored
boolean test was corrected to use the actual tuple-returning manager API before
verification; its final passing state is not claimed as a measured before/after
performance comparison.

Primary regression files: `tests/test_system_hardening.py`,
`tests/test_system_acceptance.py`, `tests/test_system_hardening_browser.py`.
The existing diagnostic login test now isolates the rejection latch between cases.

## End-To-End Acceptance Evidence

| Path / scenario | Evidence and boundary |
|---|---|
| Actual signal lifecycle | A real VWAP/EMA detector on deterministic minute fixtures produces a confirmed candidate; arbitration/risk select it; a strictly later observed tick fills at 103.25, not the 103 reference; simulated exit 109.75 yields $24 net for two MNQ after explicit fees. No broker call. |
| Arbitration matrix | Single, same-direction support, opposing directions, simultaneous indices, no candidate, expired signal, insufficient budget, closed session, missing history, stale quote, invalidating price jump, disconnected/unresolved state and rollover. Every candidate has a deterministic explanation; an empty candidate set legitimately has no candidate decision. |
| Existing exposure | Portfolio risk, reservations, forward-paper and executor suites cover occupied symbols, correlated limits, additional-symbol sizing, opposite exposure, unowned/mismatched positions and pending orders. |
| Causality and gaps | Existing backtest/replay tests mutate future bars, reject incomplete/incorrect-contract sources, and close after gaps only at later observed prices. No invented quote or target fill. |
| Reconnect / recovery | Forward-paper persistence tests restore state without duplicate fills, reject racing writers, and audit late observations. Browser reconnection is tested separately from unverified provider reconnection. |
| Exact-account execution | Practice and Leader command/preflight suites verify independent authorization, direct worker commands, account switching and durable intent barriers with mocked providers. No real account was armed. |
| Failure safety | Existing suites exercise duplicate claims, unknown submissions, missing protection, partial position mismatch, failed/unconfirmed closes, timeouts, loss lock, emergency and concurrent reservations. The new tests add malformed provider data and replay storage/startup faults. |

Seven strategy adapter routes and individual strategy tests are covered, but this
is not seven complete real-market strategy campaigns. The acceptance matrix uses
explicit candidate fixtures; the separate indicator lifecycle exercises actual
signal detection. No claim of all possible pattern combinations or market regimes.

## Profit Protection

`profit_reversals()` compares all ten prespecified configurations covering baseline,
fixed targets, break-even, ATR/structure trailing, profit lock, partial and hybrid
management. Five peaks (+0.5, +1, +1.5, +2, +3R), two directions and ten variants
produce **100 deterministic reversal scenarios**. Checks include whole-contract
conservation, fees/net accounting, monotonic stops, MFE, MAE, giveback and explicit
software-only protection labels. Closed trades do not absorb later observations.

The coarse reversal jumps can gap through software stops. A tightened stop is not
a guaranteed fill at that level. ATR/structure policies deliberately cannot invent
missing completed bars; the existing management integration tests separately
exercise completed ATR/structure history and reject future data. These fixtures do
not establish that any exit policy is more profitable than another.

Broker-side amendments/partial execution are still blocked by
`position_protection.broker_transport`. Mock reconciliation tests are not independent
validation of ProjectX OCO replacement, resizing or partial-fill behavior.

## Replay And Simulation Parity

The replay/backtest tests compare complete state/accounting for the same minute
fixtures. Playback speed, explicit pause/resume/restart, restored checkpoints and
optimistic revision fencing are tested. Restart creates a new session, preserving
the old record. Forward-paper shares the causal kernel and has separate restart,
next-observation, expiry, fill revalidation and partial-accounting tests.

This is shared-kernel consistency, not an independent second implementation.
Minute OHLC cannot reveal the true intrabar path: old-stop-first ambiguity and
next-bar trail activation are intentional. Actual recorded ticks are a distinct,
reconciled source and require strictly later observations for pending fills.
Neither data mode invents historical ticks. Arbitrary OHLC/tick equivalence is
neither expected nor asserted.

## Error Handling And Recovery

- Broker timeouts/malformed submissions retain durable intent or unknown state.
  Never resubmit simply because a response or database write failed.
- Missing/unverified protection blocks new entries and follows the existing
  owned-position close/reconciliation path. A failed close stays unresolved;
  there is no blind repeat of an uncertain close request.
- Confirmed rejected credentials are latched per process. Repair the credentials,
  or explicitly restart the relevant worker after provider permissions recover.
  The explicit read-only diagnostic probe remains available without authorizing
  trading. Transient/unknown authentication failures are not permanently latched.
- If replay storage fails, playback stops and a pending generation-fenced pause is
  retained in memory. Once storage returns, inspection/control persists the pause.
  If the process also dies, that in-memory evidence is lost: inspect the last
  committed checkpoint and explicitly pause/restart; never infer playback resumed.
- Database corruption, disk-full recovery, power loss across real submissions and
  provider-side unknown outcomes are **not** certified by temporary SQLite tests.
  Preserve files/checkpoints and require operator review rather than deleting locks.
- Invalid local HTTP inputs and browser frames produce sanitized failures.
  UI reconnect success proves local-interface recovery, not fresh market prices.
  Feed source timestamps and executor freshness checks remain mandatory.

Diagnostics classify closure independently from API health, use bounded read-only
allowlisted probes, and do not restart workers. Actual provider authentication,
entitlement, history availability and stream subscriptions were not probed here.

## Measurements

Commands: `python -m tests.benchmark_system_hardening` and
`python -m tests.benchmark_offline_replay`. All figures are local synthetic
fixtures, not production latency guarantees or profitability evidence.

| Measurement | Result / limits |
|---|---|
| Three-candidate manager, 100 runs | Median 0.211 ms; p95 0.403 ms; max 0.703 ms. |
| Seven actual adapters, 30 runs | Median 56.907 ms; p95 59.837 ms; max 147.296 ms. Constant-price 180-minute context, no selected trades. |
| Seven-strategy 180-candle historical pass | 27.843 s wall, 27.453 s CPU, 6.745 MB peak **Python-traced allocations**, tracemalloc enabled. Not process RSS, not provider or production tick latency. |
| 10,000-candle kernel | Preparation 0.078 s; batch 43.049 s; 100 checkpoint batches 44.149 s; exact final-state parity. **No participating strategies**; excludes persistence/UI. |
| SQLite read during writer, 100 samples | Median 0.350 ms; p95 0.951 ms; max 51.768 ms. Temporary small replay DB. |
| SQLite write with reader, 30 samples | Median 4.159 ms; p95 26.159 ms; max 30.211 ms. No observed lock error. Not a production-scale contention test. |
| Cached empty API snapshot, 100 requests | Median 2.599 ms; p95 3.214 ms; max 3.690 ms. In-process TestClient, warmed cache, not network RTT. |
| 20 playback start/pause cycles | Median 238.348 ms; p95/max 271.207 ms including ownership/source/code verification and joining the stopped thread. Final state paused; no leaked active player. |
| Browser stream failure recovery | Four malformed-frame cases recovered around 1.1 s in the initial headless run; one document load and no uncaught JS error. Additional responsive test output is local verification evidence. |

Adapter evaluation dominates pure arbitration in these fixtures. Replay calendar,
adapter and persistence costs must not be extrapolated from the much faster pure
manager measurement. No performance improvement is claimed: there was no
controlled before/after production comparison. The EMA repair removes a redundant
chart query but is a correctness fix, not a demonstrated speedup.

## Tests

Base regression: **487 tests passed in 134.652 s**. Intermediate post-fix run:
502 passed in 117.494 s. These timings are not a speedup claim; workloads and local
load differ. Final suite/build/browser results are recorded below at completion.

- `python -m unittest discover`: **504 tests passed in 98.189 s**, zero failures
  or errors. Seventeen additional test methods versus the audited base.
- `npm.cmd --script-shell=cmd.exe run build`: TypeScript and Vite passed; initial
  final JS gzip 97.04 KB, separate chart dependencies remain lazy chunks.
- Replay/Diagnostics: six viewport sizes, nonblank candle/volume/overlay pixels,
  persisted stepping/play/pause, sanitized rejected-auth fixture; no account writes.
- Validation Lab: six sizes, both profiles, all seven selectable strategies,
  five research tabs, saved result/trade charts; temporary data only.
- Strategy Manager: six sizes, both profiles, shared controls, save/reload, paper
  remains off; no broker action.
- Trade Management: six sizes, both profiles, four tabs, quantities/settings,
  failed-save draft retention; no broker calls.
- Full native pages: eight pages at six sizes (48 page/viewport combinations),
  nonblank price/volume/RSI canvases, no horizontal overflow or uncaught JS errors.
  Navigation median 26.985 ms across all 48 measured actions; range 15.66-360.36 ms
  includes slower mobile drawer interactions and initial page data loads.
- Four malformed stream cases: 1,052-1,074 ms recovery in the final browser run,
  one document load, no page errors or broker/account writes.

Existing non-failing warnings: Starlette/httpx deprecation, Streamlit bare-context
and deprecated container-width warnings, pandas future compatibility warning.
Dependency upgrades were not mixed into this safety milestone.

## Operational Readiness

| Area | Status | Requirement before escalation |
|---|---|---|
| Strategy correctness | Partially verified | Seven strategy-specific offline suites; no independent market calibration or profitability proof. |
| Data reliability | Partially verified | Fixture integrity, contract provenance, gaps/freshness and causal use tested. Genuine provider coverage/volume and live latency unverified. |
| Execution safeguards | Partially verified | Mocked/direct-command/reconciliation tests pass; real timeout/partial/protection races need independent broker evidence. |
| Risk controls | Partially verified | Deterministic budget, exposure, loss lock, cooldown and restored-state checks. Broker account-loss/slippage behavior unverified. |
| Profit management | Partially verified | Software simulation and 100 reversals verified; broker amendments/partial execution blocked. |
| Replay integrity | Verified | Within documented fixture, source/version, causal ordering and OHLC/tick limitations. |
| Database recovery | Partially verified | Transactions, revisions, contention and injected replay failure recovery tested. Persistent corruption/power loss not tested. |
| ProjectX access | Not tested | No real authentication/history/order probe; provider availability/permissions remain unknown. |
| Trading-calendar validation | Partially verified | Offline calendar/DST/early-close/review guards tested. Current operator-reviewed official schedule not validated in this audit. |
| Offline research | Verified | Controlled, isolated fixture research with explicit costs and source provenance; real dataset validation still required. |
| Forward-paper | Partially verified | Ready for supervised testing with verified data, frozen costs/config and reviewed calendar. Sustained fresh-feed performance not tested. |
| Practice execution | Blocked | Independent provider, exact-account, protection and recovery validation before any activation. |
| Leader execution | Blocked | Same gates as Practice, plus explicit exact-leader/copier verification and independent authorization. |

Practice and Leader retain the same strategy/control capabilities but separate
permissions and account locks. A successful Practice test must never silently arm
the Leader. Neither profile was activated during this audit. Previously recorded
worker PIDs were absent during a passive check; this is not proof that all current
workers are stopped or healthy. No worker was started to investigate.

Before any deployment: preserve local data/settings; review changes; use the
manual launcher; verify source timestamps/contracts/calendar; test read-only
provider access; independently validate exact-account protection and recovery;
review all unresolved jobs/locks; then make an explicit authorization decision.
Do not deploy this update over an active broker position without a controlled,
broker-flat handover and operator review.

## Delivery

Logical commits and the remote branch are recorded in the delivery response.
`main` is unchanged. No merge or automatic activation is part of this phase.
