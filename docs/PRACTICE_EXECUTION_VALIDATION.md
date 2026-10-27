# Phase 9: Practice Execution Validation

## Verdict

**Read-only ProjectX integration and mocked validation passed. Actual Practice
entry/exit validation is BLOCKED and was not performed. Leader is NOT READY for
activation on the strength of this milestone.**

Observed October 26, 2026, America/Chicago. Final explicit read-only preflight:
17:11:18 CT / 22:11:18 UTC. Evidence is a timestamped observation, not an ongoing
health guarantee or an authorization to trade.

Audited implementation: `c0b36cf` on `feature/practice-execution-validation`.
Fetched remote branches before work; the latest starting branch was
`feature/operational-acceptance` at `9d5b07c`. Existing dashboard, credentials and
system-control changes were preserved in baseline commit `99d804f`, not discarded
or silently mixed into the validation changes. No merge into `main`.

## Scope And Preserved State

- The exact configured Practice identity matched exactly one authenticated
  provider account. It was API trading-enabled and simulated. Account name, ID,
  balance, credentials and session token are intentionally omitted here.
- That exact identity match is **not independent proof of Practice category**.
  The actual provider record contained only `id`, `name`, `balance`, `canTrade`,
  `isVisible` and `simulated`; no category/type discriminator or bracket mode.
- Practice was already enabled with all seven strategies selected at inspection.
  The operator explicitly approved pausing **new Practice entries** in this chat.
  That pause was performed. Workers and exit management were left running.
- Leader remained paused. No Leader/funded configuration, copier configuration,
  sizing, strategy selection, stop interval, execution calendar, run-loss limit,
  $500 persistent loss lock or balance was changed/reset.
- After the approved pause, a consistent SQLite backup and private local account
  configuration copies were preserved under ignored
  `data/verification/phase9-preserved-state/`. Subsequent comparison confirmed
  control settings, strategy settings, bot controls and persistent loss-gate rows
  unchanged. Account/copy files matched their preserved SHA-256 hashes.
- No broker entry, close, cancellation, modification, partial close, account
  reset, account arming or trading-worker restart was issued during Phase 9.
- No UI redesign, strategy addition or automatic multi-strategy activation.

## Actual Read-Only Provider Results

These are genuine authenticated requests, not mock responses. The final preflight
reused one newly authenticated token, with one request per operation and no retry.
Raw payloads, provider error text, account identifiers and token are not logged.

| Operation | Final outcome | Response time |
|---|---|---:|
| API-key authentication | PASS | 197.88 ms |
| Account search / balance read | PASS; exact designated identity and eligibility matched | 197.51 ms |
| Practice open positions | PASS; zero positions | 182.42 ms |
| Practice working orders | PASS; zero orders | 184.07 ms |
| Active MNQ contract search | PASS; one active exact micro | 174.79 ms |
| Available contracts | PASS; current MNQ included | 176.90 ms |
| One-hour bounded historical request | PASS; 11 completed minute bars returned and validated | 199.95 ms |

Active contract observed: `CON.F.US.MNQ.Z26`, resolved from ProjectX rather than
hardcoded. Verified `symbolId=F.US.MNQ`, tick size 0.25 and tick value USD 0.50
(USD 2 per point). Contract rollover is rejected if quote/trade contract differs.
History was validated in memory and not written into production history.
Eleven bars do not establish complete strategy lookback/session coverage.

The market stream reported connected. Contract-matched MNQ bid/ask and trade
observations had current source and receipt timestamps. Final source ages were
1.688 seconds for quote and 1.732 seconds for trade; invalid/future/stale stamps
are not treated as fresh.

The standard exchange clock and existing execution schedule were open, in the
Overnight session. **An operator-reviewed exchange calendar was not configured**,
so holiday/exception-aware entry permission was not positively established.
Fresh ticks and a normal clock window do not bypass that gate. The existing
14:50 CT entry cutoff and 15:05 CT flatten buffer remain unchanged.

The original $500 loss gate was readable and unlocked, with current balance above
its loss threshold. The existing run-loss gate passed. Both execution profiles
were paused and there were zero unresolved local execution jobs. This evidence
does not create or reset a baseline.

## Actual Execution And Approval Ledger

| Item | Actual outcome |
|---|---|
| Order-specific entry approval | NOT OBTAINED; general Phase 9 authorization is not sufficient |
| Approved side, quantity, stop, cost estimate | NOT PROPOSED; preflight blockers prevent an executable proposal |
| Entry intent / submission / broker order ID | NOT PERFORMED / none |
| Fill / actual entry / position quantity | NOT PERFORMED |
| Original broker protective stop / ownership | NOT TESTED; no test position opened |
| Fixed target / trail / amendment / partial transport | NOT TESTED against broker; experimental paths remain disabled |
| Separate full-close approval / request / acknowledgment | NOT OBTAINED / NOT PERFORMED |
| Post-test broker close / cleanup reconciliation | NOT PERFORMED; read-only preflight independently observed flat |
| Actual fees, commissions, slippage, realized P&L | NOT AVAILABLE; no values inferred from fixtures |
| Practice test orders / Leader test orders | 0 / 0 |

No successful-trade claim is based on an accepted submission, an order ID, a local
Closed job or a disappearing order. A future test must reconcile actual fills,
owned protection, full-position close, residual orders and attributable fees/P&L.
Unknown outcomes must never be automatically resubmitted.

## Validation Command And Audit Evidence

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation
```

The default is read-only. It reports readiness, sanitized timestamps/status codes,
request timings and exact blockers, and writes
`data/verification/practice-execution-readonly.json`. Blocked readiness returns
nonzero (the Python entry point returns 2). It never arms accounts or invokes a
worker. Importing either validation module does not authenticate or call ProjectX.

`--request-order` is deliberately **not a submission flag**: it repeats read-only
preflight and exits blocked. No real-entry or close transport was added while
account-category and bracket-mode verification are unavailable. There is no
approval-string escape hatch around these blockers. Implementing the actual
one-contract order-level approval/intent/reconciliation command is deferred until
those provider facts can be reliably verified. Thus Phase 9's real-order portion
is incomplete, not silently simulated or waived.

`ReadOnlyBroker` allowlists only authentication, account search, exposure searches,
contract discovery and history retrieval. Place/close/cancel/modify/arming paths
are rejected before transport. Each response must have boolean success, a valid
provider error code and the expected collection/object schema. Exposure rows must
match the requested Practice account. Rejections/timeouts are sanitized without
automatic retries. Failed authentication invalidates the probe's prior token.
No credentials, raw response or unnecessary account identifiers enter the report.

The old `scripts.practice_smoke_test` alias has been removed. Use this canonical
diagnostics entry point. The former unconfirmed MES entry and automatic close
are not available through the retired alias.

## Mocked Pipeline And Failure Results

**All results below are synthetic fixtures, not real Practice execution.**

- All seven catalog strategies: CRT, Reversal, ORB, VWAP Reclaim, EMA Pullback,
  VWAP EMA Cross and Previous Day Box Reversal passed candidate registration,
  confirmation, expiration, arbitration, exact-profile isolation, portfolio loss
  lock and consumption/duplicate checks. Both LONG/SHORT payloads map to one MNQ
  contract with the correct side and protective bracket. The two newer strategies
  additionally passed generated canonical/frozen envelopes through the existing
  payload builder. Their real broker/calendar/opt-in state was not changed.
- Existing strategy generation/session/indicator tests remain in the complete
  regression suite. Research/shadow eligibility never authorizes broker cutover.
- Existing executor mock round trip: actual-fill recording, adverse slippage,
  parent-linked opposite-side equal-size stop, existing full-close pathway and
  subsequent flat-state reconciliation passed. Fixture fill 100.50 versus
  reference 100.00 gives +0.50 adverse points; this is not a real trade result.
- Delayed fill stayed Submitted; absent unobserved fill became Unknown, never an
  invented completed trade. Rejected/unknown submissions were not retried.
- A duplicate or restored pending claim could not produce a second entry.
- Partial/mismatched position quantity paused for review. Existing multi-contract
  partial-exit research tests passed with mocks only; broker partials were not
  enabled or attempted.
- Missing broker protection invoked the existing owned-position full-close
  safety path under mocks. Wrong account, parent, side or size was not protection.
- Unowned positions were not closed; unrelated/orphan orders were not canceled
  and were not mistaken for flat. Unknown close responses remained Closing and
  were not automatically resent.
- Authentication rejection, network timeout, malformed/incomplete responses,
  stale/future/wrong-contract prices, session closure, missing reviewed calendar,
  persistent risk-lock activation and unrecognized exact identities failed closed.
- Existing connection-loss/reconnect, restart/replay, profit protection and
  duplicate-prevention tests passed. There was no deliberate broker fault injection.

## Confirmed Defects And Changes

1. The legacy smoke script could place an MES market order and automatically close
   without specific entry/close approval. It also accepted weak protection evidence
   and did not establish independent Practice category. It is now read-only.
2. Three regression fixtures depended on the absence of private local account
   overrides. Account-label tests globally mocked `Path.read_text`, the Leader
   subprocess compared a current executor to legacy targets, and first-run tests
   read the real account directory. Scoped temporary copy/identity paths and the
   authoritative current identity fixed those assumptions. No runtime account
   restriction was relaxed.
3. Added a strictly read-only preflight with sanitized response parsing and timing,
   read-only SQLite safety inspection, current active MNQ/bid-ask/trade checks,
   explicit category/bracket/approval blockers and 31 isolated validation tests.

## Exact Verification Results

| Verification | Result |
|---|---|
| Initial full regression | 556 tests; 2 failures, 1 error from local-account fixture assumptions |
| Focused corrected account/Phase 9 tests | 49 tests passed before the final four new tests |
| Final Phase 9 test module | 31 passed, 0 failures/errors |
| Final `python -m unittest discover` | **560 passed, 0 failures, 0 errors, 0 skips; 94.973 seconds** |
| `python -m compileall -q goxtrade scripts tests` | PASS |
| `npm.cmd --script-shell=cmd.exe run build` | PASS; existing Three.js chunk-size advisory remains |
| `tests.test_system_hardening_browser` | 6 viewports x 8 pages; no overflow/page errors; nonblank charts; 4 stream-fault recoveries; no document reload; zero broker writes |
| `tests.test_dashboard_3d_browser` | 6 viewports; nonblank, interactive, resizable chart; negative/empty data and WebGL fallback; zero mutations/errors |
| Saved production safety/config comparison | PASS after approved pause; no further settings/risk/account/copy changes |

Private logs/screenshots/backups remain ignored under `data/verification/`. The
application interface was not redesigned and no account worker was restarted to
deploy Phase 9; this is an independently invoked read-only command.

## Remaining Blockers And Readiness

1. Obtain an independently verifiable provider-supported Practice category, bound
   to the exact allowlisted identity. A local name, screenshot designation or
   `simulated=true` alone is insufficient for the requested strict test standard.
2. Establish this exact account's Auto OCO bracket mode without a speculative order.
   Do not disable original protection or send an unprotected entry as a workaround.
3. Supply a fresh operator-reviewed CME calendar using the existing configuration
   workflow; do not invent an exchange-open override for a test.
4. Only then implement and review the explicit one-MNQ approval/intent/submit/fill/
   protection/monitor command and obtain its exact-account, side, stop, quantity,
   cost/exposure confirmation. Obtain a separate explicit approval for full close.
5. Complete a genuinely supervised Practice round trip and attribution before
   assessing supervised Practice automation. Passing fixture research is not
   evidence of profitability, signal quality or broker readiness.

**Supervised Practice automation: NOT ACCEPTED by this milestone. Leader:
NOT ACCEPTED / NOT ENABLED.** The designated Practice account was left flat and
paused; Leader remained paused. Resettable Practice status is not a reason to
bypass any verification, calendar, authorization or loss lock.

## Primary References

- [ProjectX account search](https://gateway.docs.projectx.com/docs/api-reference/account/search-accounts/): documented account response, not independent Practice-category proof.
- [ProjectX contract discovery](https://gateway.docs.projectx.com/docs/api-reference/market-data/search-contracts/): active-contract metadata and tick specifications.
- [ProjectX order/bracket requirements](https://gateway.docs.projectx.com/docs/api-reference/order/order-place/): Auto OCO required for attached brackets; a rejected order may still have an ID.
- [CME MNQ contract specifications](https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html): instrument identity and tick/point value.
- [Topstep trading hours](https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade): provider schedule limits; existing conservative buffers retained.
