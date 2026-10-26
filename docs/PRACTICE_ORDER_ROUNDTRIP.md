# Phase 10: Controlled Practice Order Round Trip

## Delivery And Actual Outcome

Base: `12b86e5` / `feature/practice-execution-validation`, fetched and inspected
before work. Delivery branch: `feature/practice-order-roundtrip`. Audited
implementation revision: `cb8fa3c` (initial implementation `993972a`). No automatic merge into `main`.

**The gated functionality is implemented and mock-tested. No real Practice entry,
full close, cancellation or modification was authorized or submitted in Phase 10.**
Default/readiness actions did not create a review, proposal or production intent.
No trading worker was restarted, stopped or changed. No account identity, copier,
permission, strategy, sizing, history, calendar configuration or loss lock was
rewritten/reset. Practice and Leader were paused at the read-only inspection.

The operator supplied an Auto OCO screenshot and confirmed the mode applies to
both configured accounts. This is useful provider-settings evidence, but the
cropped screenshot does not display the selected immutable account identifier or
Practice reset/category information. It was **not automatically turned into a
completed account-bound review or trade approval**. The operator-review workflow
below binds and records that evidence explicitly. No inference from a PRAC name
or `simulated=true` substitutes for provider account-management evidence.

The current controlled readiness action correctly reports:

> BLOCKED: Missing, expired or changed exact-account provider/Auto OCO operator review

The reviewed calendar and order-specific approvals are also outstanding. The
user has not selected a test side, stop distance, fee estimate or risk cap, so
there is no approved executable proposal to transmit. General statements that
settings are good do not approve an entry or close.

## Reliable Account And Bracket Verification

Current official Gateway account search still does not expose a reliable
Practice/Combine/XFA discriminator or bracket-mode field. The fallback is an
explicit **operator review of provider evidence**, not an invented API field:

1. Open Topstep account management. Inspect the exact designated resettable
   Practice account, not a Combine, funded/XFA, Leader or another account. Verify
   its name against the authenticated API record and its numeric account ID shown
   by the review command. Never choose the first account in a returned list.
2. Supply a provider screenshot/PDF showing that account's Practice category/reset
   capability. Do not reset it. Supply the account-specific Auto OCO Risk Settings
   evidence as a second screenshot/PDF; the selected account must be unambiguous.
3. Confirm that this Practice account is isolated from copiers and concurrent
   manual trading. No copier configuration is changed by this tool.
4. The review command queries the exact current identity, checks broker-flat state,
   displays the immutable identifier privately, and requires a fresh interactive
   `VERIFY PRACTICE <id>` confirmation. Evidence paths/hashes, official source,
   API origin, immutable account/configuration digest and review/expiry times are
   bound together. Review validity is 30 minutes; changed evidence/identity/origin
   requires a new review. Credential values and approval input are never saved.

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation `
  --mode review-account `
  --account-evidence "C:\path\provider-practice-category.png" `
  --oco-evidence "C:\path\provider-account-oco.png"
```

Run interactive actions in a real operator terminal, not a background task.
Evidence documents must be nonempty image/PDF files no larger than 10 MiB.
Official provider HTTPS source URLs cannot contain credentials/query secrets.
Images are not automatically interpreted as verified classifications; the human
must inspect and affirm them against the exact authenticated account.

Topstep distinguishes Position Brackets and Auto OCO. Gateway attached brackets
require Auto OCO; a rejected bracket request may still return an order ID.
Neither acknowledgment nor the platform mode proves a stop was actually created.
The supplied screenshot's trailing-stop presets are **not modified or assumed to
be MNQ API order presets**. This test sends its own required static stop bracket
using the existing order builder (`type=4`), with no take-profit bracket or stop
amendment. Stop distance must be at least six whole ticks, a conservative test-only
minimum from Topstep's documented greater-than-five-tick bracket guidance. Regular
strategy settings/minimums remain unchanged.

## Calendar Review Without A Global Override

Use an actual operator-reviewed JSON file in the existing calendar schema:
`schema_version=1`, `timezone=America/Chicago`, official CME `source_url`,
`product_group=US equity index futures`, actual `reviewed_at`, `valid_from`,
`valid_until` and explicit timezone-aware `sessions` open/close pairs.

Verify MNQ weekly hours, daily maintenance, holidays and early closes against the
official CME schedule before approving. The tool does not generate a supposedly
reviewed calendar, insert assumed dates or mark the supplied screenshot as a
calendar review.

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation `
  --mode review-calendar --calendar "C:\path\actually-reviewed-calendar.json"
```

The existing `calendar_guard.validate` enforces source, schema, coverage,
non-overlap and at-most-weekly review. The full reviewed content is displayed and
requires a distinct digest-bound interactive `REVIEW CALENDAR ...` confirmation.
The file is referenced/hashed in the test review; the existing global calendar
file is not overwritten. Any change invalidates the review. Existing global
restrictions still win. Standard exchange session, weekend/maintenance logic,
14:50 CT entry cutoff, 15:05 CT flatten buffer and a 15-minute exchange close
buffer are also enforced. Closing an already-owned position is not prevented by
an entry cutoff or expired entry review.

## Default Read-Only Behavior And Readiness

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation
.venv\Scripts\python.exe -m scripts.practice_execution_validation --mode readiness
```

The no-mode command retains the conservative Phase 9 provider audit, including
explicitly unverified *API* category/bracket fields. `--request-order` is still
read-only and exits blocked, not an order flag. The new `readiness` mode evaluates
the operator-evidence alternative and actual controlled-test gates without
creating a proposal or transmitting anything. A successful readiness result means
only READY_FOR_PROPOSAL, never permission to trade.

All mutation modes are confined to the configured Practice identity and a Practice
process. Leader/funded selection, fallback accounts and identity rewrites do not
exist in this workflow. API/account-origin or exact identity changes invalidate
the evidence/proposal. Opening/importing the script never makes a broker request.
No ordinary app, scheduler, Strategy Manager or UI startup invokes order modes.

## Proposal And One-Time Entry Approval

The operator must choose every variable below; this audit selected none:

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation `
  --mode propose --side $Side --stop-ticks $StopTicks `
  --commission-per-side $EstimatedFee --slippage-ticks $SlippageTicks `
  --max-risk $RiskCap
```

`$Side` must be BUY or SELL. The proposal always specifies one MNQ market contract,
the broker-discovered active expiry, exact Practice name/ID, quote timestamp,
current bid/ask, reference entry/stop, stop ticks, positive estimated commission,
bounded slippage estimate, total planned risk, operator cap, unique test ID and
45-second expiration. A private terminal displays the exact identity; status
reports redact it. There is no automatic strategy side selection or sizing change.

For one MNQ, planned stop risk including estimates is:

`stop_ticks * USD 0.50 + 2 * commission_per_side + 2 * slippage_ticks * USD 0.50`.

It must fit both the operator cap and the remaining existing $500 account/run-loss
budgets. Existing cooldown, no unresolved orders, paused profiles, no emergency
flag, current exact MNQ contract/tick specifications, fresh contract-matched
bid/ask/trade observations and a spread no larger than two ticks are required.
For the operator's explicitly requested Phase 11 exception, controlled Practice
`readiness`/`propose` accepts `--max-spread-ticks 3`. The default remains two. This
is an immutable, digest-bound field in that test proposal, reused by every entry
preflight before/after approval and after reservation. Four ticks still blocks;
invalid limits and Leader profiles remain prohibited. Submit cannot silently
change a saved proposal's spread limit. This option never writes Practice/Leader
strategy settings, execution controls or account loss limits.
The operator also explicitly requested current market execution without a fixed
reference-price band. Practice proposals can opt into `--price-policy market`;
the default remains `bounded`. This field is approval/digest-bound. Market mode
retains fresh source/receipt times, spread, account, review, expiry, quantity,
stop and planned-risk checks; it does not guarantee actual costs or prices.
Market/stop fills are not guaranteed prices; actual costs/slippage can exceed an
estimate. The bracket is a fixed tick distance from actual fill, not a guaranteed
absolute stop level.

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation `
  --mode submit --test-id $TestId
```

Submit rechecks the proposal, displays it again, and requires a fresh interactive
`ENTER <test-id>` affirmation via non-echoed input. There is no `--yes`, approval
in command arguments, default approval or batch submission mode. Human input is
not persisted. Authorization is bound to the immutable account/provider origin,
contract, side, quantity, stop/cost/risk fields, evidence/calendar digests, approved
price band, expiration and unique test ID. Price movement outside that explicitly
approved band requires a new proposal/approval, not an adjusted hidden order.

## Durable Intent And Submission Isolation

Before the wire call, one SQLite transaction consumes the proposal and creates
both a test intent and an exact Practice production-job reservation. It rechecks
paused profiles and unresolved jobs under `BEGIN IMMEDIATE`. Concurrent requests
or other test IDs cannot reserve a second entry. A further complete preflight
runs after reservation; changed conditions retain a blocked reservation and send
no order. The transport then durably claims its one wire attempt before invoking
the existing ProjectX client. Missing/wrong protection, account, contract, type or
quantity is rejected at the transport boundary too.

The production reservation stays **Intent** while this explicit test owns entry/
protection monitoring. Existing strategy workers do not submit Intent records;
ordinary arming is blocked by the unresolved reservation. The separate test audit
records ACKNOWLEDGED, ACK_REJECTED, SUBMISSION_UNKNOWN, PROTECTED or UNSAFE as
actual evidence arrives. This avoids restarting/changing worker code or allowing
an automatic strategy to manage the manually approved test. An operator must
actively supervise the test; a broker stop is mandatory, not optional.

Additive tables: `practice_test_reviews`, `practice_order_tests` and
`practice_order_test_events`. Events retain complete local audit snapshots without
tokens or approval input. Production settings/history/loss tables are not reset.
The internal negative-ID reservation is an audit/ownership record, not a strategy
signal or authorization to enter another trade.

If a process dies before/after transmission, durable Intent/SENDING remains.
Neither a fresh process nor another confirmation can resend it. A timeout,
malformed response or rejected acknowledgment is not proof that no fill occurred.
Only subsequent broker evidence can resolve it. A broker-confirmed Rejected
order with zero fill and a flat/clear account can release the reservation;
otherwise manual review is required. A known pre-wire failure also remains
conservatively reserved rather than inviting an automatic retry.

## Fill And Protective-Stop Reconciliation

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation --mode status --test-id $TestId
.venv\Scripts\python.exe -m scripts.practice_execution_validation --mode monitor --test-id $TestId --seconds 30
```

These actions only query/reconcile. Monitoring is bounded by a requested time
window and existing per-request network timeouts; it is not a background trader.
An acknowledgment/order ID never marks a position filled. Ownership requires the
unique entry tag, exact account/contract/side/size, broker Filled status/fill
volume, actual non-voided entry trade and matching position quantity/direction/
average price. Partial, inconsistent, future-dated or ambiguous data fails closed.

Protection must be an actual open opposite-side, equal-size stop on the same
account/contract, associated with the entry and at the requested initial
fill-relative distance. The existing strict `protective_order` verifier is reused.
It requires real parent association returned by the broker; public response
examples do not guarantee that field. If association is absent, it is **not
invented or inferred from a nearby stop**: protection remains unverified/UNSAFE.
Mode/entry acceptance alone is never shown as confirmed protection.

Actual entry/exit time and price, adverse/favorable slippage, planned risk,
broker protection, latency, quantity and flat/working-order counts are recorded.
Reported fees and realized P&L remain null if the provider does not supply them;
no estimate is relabeled as an actual broker result.

## Separately Approved Full Close And Emergency Procedure

```powershell
.venv\Scripts\python.exe -m scripts.practice_execution_validation --mode close-proposal --test-id $TestId
.venv\Scripts\python.exe -m scripts.practice_execution_validation --mode close --test-id $TestId
```

The close proposal requires a reconciled owned open position, no prior close
intent and verified protection. It binds exact identity/contract/quantity, entry
fill, full working-order details and a new 45-second expiration. A separate
interactive `CLOSE <test-id>` affirmation is required. Position/order changes or
expiry invalidate approval. A close intent and separate wire-attempt claim are
durable before the existing Practice `close_job` full-position pathway is called.
That pathway persists Closing and re-verifies the exact account before its broker
request. No partial close or stop amendment transport is enabled.

**If protection is missing/unverifiable:** the tool reports UNSAFE and stops new
testing. Promptly inspect the exact Practice position in Topstep. The explicit
`--mode emergency-close-proposal --test-id $TestId` action can prepare an emergency
full-close proposal for the independently verified owned position. It requires
its own `EMERGENCY CLOSE <test-id>` affirmation via `--mode close`; missing
protection does not authorize an unowned-position close. If ownership, API access
or local reconciliation is uncertain, use the provider interface/support rather
than guessing an account or retrying the API.

Never rerun an uncertain close. CLOSE_INTENT/CLOSE_UNKNOWN blocks another close
submission across process restarts. Status/monitor may be rerun read-only.
Completion requires a unique attributable actual exit fill, reported realized
P&L, broker-flat state and **zero** residual working orders. Stop fills can be
identified through actual parent-associated broker orders. Full-close fills must
uniquely match the approved close window/new order set in this isolated account;
ambiguous/manual unrelated exits remain unresolved.

The controller does not blindly cancel orders. The existing worker's verified
owned-stop cleanup remains available after `close_job` switches its reservation
to Closing. If any stop/unrelated order remains or cleanup cannot be proven,
status stays FLAT_RECONCILIATION_PENDING. Inspect provider orders; do not declare
completion, clear reservations or submit another entry to force cleanup. A final
COMPLETE releases only this test's production reservation after broker proof.

## Actual Phase 10 Evidence And Verification

Fresh read-only provider evidence was captured October 26, 2026. Authentication,
the exact configured eligible account, balance/loss checks, zero positions/orders,
active MNQ discovery, availability, current source ticks and historical bars were
queried without order endpoints. Full details remain in ignored
`data/verification/practice-execution-readonly.json`. One initial audit snapshot
conservatively blocked quote freshness when a receipt landed after the audit's
initial clock capture; a regression test and post-snapshot observation-time fix
corrected that read-only diagnostic race without tolerating future/stale data or
changing the collector. The order workflow already observes its clock after
reading price data.

Actual results remain: no entry approval, no entry order ID, no actual entry fill,
no tested broker protection, no close approval/request/fill, no actual test fees/
slippage/P&L. The Auto OCO image/operator statement is not an entry/close approval.
No real-order success or profitability is claimed.

- Base Phase 9 verification: 560 tests passed, as recorded in its report.
- Phase 10 focused safety + Phase 9 regression: 69 tests passed using mocks only.
- Final complete suite: **598 tests passed in 99.567 seconds; no failures or errors**.
- Python compilation: passed. TypeScript/Vite build: passed; existing Three.js
  chunk-size advisory remains; no frontend redesign or dependency changes here.
- Existing isolated UI/browser regression: six viewports x eight pages, nonblank
  charts, no page errors/overflow, four stream fault recoveries, zero broker writes.
- No GUI live-order buttons were added. The existing app/account UI is preserved;
  the dedicated, Practice-only CLI displays readiness, complete proposals,
  approvals, protection/position state and last reconciled report without exposing
  a Leader selector or an automatic UI/network submission action.

Mocked tests cover wrong/Leader/funded/ambiguous identity, missing or expired OCO
review, changed evidence, invalid stop/side/cost/risk, malformed boolean broker
enums/quantities/fill volumes, stale
prices, closed market, unreviewed/global-restricted calendar, occupied account,
unknown orders, loss lock, strategy permissions, duplicate/expired/modified
proposals, rollover/price change, explicit refusal, rejection with order ID,
rejection despite actual fill, delayed/malformed/unknown response, missing
protection/emergency approval, partial/unowned positions, orphan orders, missing
fees/P&L, restarts during entry/close, concurrent same/different test requests,
wire-level duplicate denial, existing full-close adapter and noninteractive
approval refusal. Automated tests never send real orders.

## Remaining Blockers And Next Readiness

1. Complete the fresh exact-ID operator review using provider Practice category/
   reset evidence and account-bound Auto OCO evidence. The supplied image and
   general confirmation are not yet a completed review record.
2. Approve actual CME calendar content; no reviewed calendar was fabricated or
   existing trading restriction bypassed in this milestone.
3. Choose the test side, stop ticks, explicit fee/slippage estimates and planned
   risk cap. Review the resulting one-MNQ proposal and separately approve entry.
4. Reconcile an actual fill and broker stop before separately approving full
   close. Missing parent association/protection or unknown broker outcomes must
   be reviewed, not guessed or retried.
5. Confirm genuine flat/clean outcome and fees/P&L attribution before assessing
   readiness for strategy testing. Passing mocks is not that acceptance.

**Real round-trip validation: NOT PERFORMED / BLOCKED on operator prerequisites.
Automatic strategy testing and Leader activation: NOT AUTHORIZED.**

## Phase 11 Operational Attempt: October 26, 2026

Fetched `origin` and confirmed the clean delivery branch matched `1cfc71d` before
the attempt. Reused the existing CLI and read-only broker adapters; no new order
system or transport was introduced. Inspected the account/OCO/calendar reviews,
proposal/approval gates, durable intent, entry/stop reconciliation and separately
approved close/emergency/recovery paths. No strategy, copier, account assignment,
position limit, loss control or worker state was changed.

The genuine default preflight at 18:08:05 CT authenticated successfully and
matched the exact configured Practice identity with provider trading eligibility.
The balance and configured loss/run gates passed. Broker state was zero positions
and zero working orders; there were zero unresolved local execution jobs. Both
Practice and Leader entries remained paused. No Leader order operation occurred.
The API still does not establish Practice category or Auto OCO mode independently.

Active broker-discovered contract: `CON.F.US.MNQ.Z26`, tick size 0.25, tick value
USD 0.50. The market stream was connected. Quote/trade source ages were 1.781 /
1.909 seconds at the default audit snapshot; 60 historical bars were read without
saving them into production. A separate read-only snapshot at 18:08:43 CT showed
a two-tick bid/ask spread with current quote/trade receipts. These snapshots are
observations, not an executable proposal or a promise of future market prices.
Exact account identifiers and balance were shown privately to the operator, not
exported into this committed guide.

The standard session and existing execution schedule reported Overnight/open.
Official CME trading-hours and Topstep permitted-hours sources were consulted;
clock-window eligibility and fresh prices were not substituted for a reviewed
exchange calendar. No global calendar file or test calendar review was present.
No exact-account operator review was present. The existing `--mode readiness`
command therefore correctly blocked on the missing exact-account provider/Auto
OCO operator review before any proposal or order could be created.

Requested from the operator: provider evidence showing this designated account's
Practice category/reset capability and its selected-account Auto OCO Risk Settings,
plus copier/manual-trading isolation confirmation. The prior general statement
that OCO applies to both profiles was retained as a statement, not fabricated
account-bound evidence. Also requested BUY/SELL, stop ticks, commission per side,
slippage ticks and the maximum total planned risk. No side was chosen by a strategy.

**Entry proposal: not created. Entry approval: not obtained. Entry transmission:
none. Actual fill/protective stop: not tested. Separate close approval/request:
none. Final observed broker state: flat with zero working orders at preflight;
not a completed round trip. Actual execution fees, commissions, slippage and P&L:
not available because no test order occurred.** No broker failure was observed;
remaining blockers are provider evidence/review, an actual reviewed calendar,
remaining proposal inputs and fresh separate entry/close approvals. Automated Practice
strategy acceptance remains unestablished and strategies were not enabled.

The read-only JSON evidence remains local in the existing ignored artifact
`data/verification/practice-execution-readonly.json`. Phase 10's 598-test result
above is historical verification, not a new Phase 11 real-order result. This
attempt stops at the authoritative prerequisite gates without weakening them.

The operator subsequently selected **SELL** and confirmed the requested Practice/
OCO/isolation statement in chat. This selects the direction only, not entry
approval. No new account-bound provider attachment, stop distance, commission,
slippage allowance or risk cap accompanied the response; the supported review
and proposal gates remain incomplete. No review or approval was synthesized.

### Follow-Up With Account-Specific Screenshot

The operator subsequently supplied the full provider screenshot with the exact
configured Practice account selected, matching balance, explicit $150K PRACTICE
category and Auto OCO Risk Settings visible together, and repeated the request
for one MNQ SELL. Combined with the operator's reset/isolation confirmation and
explicit authorization to complete the review workflow, this established the
previously missing account-bound evidence. Codex completed the existing interactive
`review-account` command using that image for both evidence references. The stored
basis is OPERATOR_REVIEWED_PROVIDER_EVIDENCE, not a new provider API discriminator.
The review expires at 18:45:02 CT. No entry confirmation was entered.

Codex also performed the authorized source review against CME's Micro E-mini FAQ
and published 2026 Globex holiday schedule, and the existing Topstep permitted-hours
source. October 26-27 is outside the listed Globex holiday windows. The reviewed
file covers only October 26 at 17:00 CT to October 27 at 16:00 CT, with the CME
15:15-15:30 CT halt excluded. The existing earlier Topstep cutoff/flatten gates
continue to apply. The actual review timestamp is 18:15:25 CT. The existing
interactive `review-calendar` command recorded the file/digest; the global
calendar file was not created or changed. Local source-review artifact:
`data/verification/phase11-reviewed-session.json`. No claim is made that the
human personally entered the CLI review phrases; Codex performed those non-order
reviews under the operator's authorization and supplied evidence/confirmation.

After reviews, `--mode readiness` blocked on the live bid/ask/tick-grid gate.
A single subsequent `--mode propose` attempt used SELL, one MNQ, 100 stop ticks,
USD 1 estimated commission per side, two estimated slippage ticks per side,
USD 54 planned risk and USD 60 cap. These were disclosed candidate test inputs,
not operator-approved entry details or altered account limits. The same live
gate blocked before a proposal was persisted. At 18:16:33 CT the local source
snapshot showed bid 29,426.25 / ask 29,427.00, or three ticks. Bid, ask and trade
were on valid 0.25 increments. The existing maximum is two spread ticks; it was
not widened. Quotes are historical observations, not current executable prices.

**Follow-up outcome: evidence/calendar reviews completed; no executable proposal,
entry authorization, entry transmission, fill, tested stop, close request or
execution costs. Current blocker: live spread gate. Automatic entries remain
paused.** The next preparation attempt must revalidate current quotes and all
reviews, then display a fresh one-time proposal for specific operator approval.

### Actual Authorized Entry And Full Close

This supersedes the earlier blocked-attempt outcome, not the historical Phase 10
results. The operator explicitly allowed a three-tick spread for this Practice
test only and requested market-price execution regardless of reference-price
movement. Added bounded, proposal-specific CLI options described above; no regular
Practice/Leader policy, account assignment, strategy, size, loss limit or copier
configuration was changed. Tests verify default two-tick/bounded pricing,
digest-bound explicit exceptions, all final preflights, retained fresh-data/stop/
risk checks, duplicate denial and Leader exclusion. The three-tick revision passed
601 full tests in 115.974 seconds. The subsequent market-price revision passed
75 focused Phase 9/10 safety tests and the final full suite passed **604 tests in
117.451 seconds**, with no failures/errors. Python compilation and diff checks
passed. Final suite output: ignored local
`data/verification/phase11-unittest-final.log`. Mocks are not counted as broker
acceptance; the real order evidence below is recorded separately.

An initial approved bounded-price proposal was rejected before transmission
because the market moved outside its disclosed price band. No intent or wire
attempt was created for that proposal. A new proposal explicitly disclosed market
pricing without that reference band, one MNQ SELL, 100 stop ticks, USD 1 estimated
commission per side, two estimated slippage ticks per side, USD 54 planned risk,
USD 60 estimated-risk cap and maximum three spread ticks. Actual losses/fills
were expressly not guaranteed by that estimate. The operator approved that exact
test ID and expiration before the existing submit confirmation was entered.

Test ID: `4229a01be83c49b88a716cd3411983fb`.

- Account: exact authenticated designated resettable Practice; identifiers remain
  private in the local audit, never a Leader/funded/evaluation fallback.
- Contract: `CON.F.US.MNQ.Z26`, SELL one market contract.
- Entry broker order: `3686444578`, actually filled 29,455.00 at broker timestamp
  October 26, 18:23:48.448858 CT. Provider code 0; acknowledgment 220.15 ms.
- Required stop: broker order `3686444579`, BUY stop, size one, type 4, Open,
  parent `3686444578`, stop price 29,480.00. Exact account/contract, quantity,
  direction and 100-tick fill-relative distance were independently reconciled.
  The test reached PROTECTED; initial reconciliation took 1,081.91 ms.
- Entry reported fees: USD 0.36. Fill was three points adverse to the proposal
  snapshot 29,458.00. Because the approved market policy allowed reference movement,
  this measures snapshot-to-fill movement, not isolated network/exchange slippage.
- The separately approved first close expired during final rechecks and sent no
  close request. A refreshed full-close proposal received new explicit approval.
  Its CLI `direction` field reflects the open SELL position; the operator-facing
  approval correctly specified BUY TO CLOSE, and the broker confirms BUY. This
  labeling mismatch should be corrected before broader operator acceptance.
- Durable full-close intent: 18:26:08.092725 CT; close wire claim recorded before
  the existing exact-account full-position close route. Close acknowledgment was
  421.42 ms. No repeat close or experimental cancellation was sent.
- Actual exit: broker order `3686456650`, BUY one, Filled, fill volume one,
  29,462.25; nonvoid broker trade `3245723239` at 18:26:06.976230 CT.
- Provider-reported realized P&L: USD -14.50, independently consistent with
  (29,455.00 - 29,462.25) x USD 2/point. Exit reported fees: USD 0.36; total
  reported entry/exit fees USD 0.72; net of those reported fees USD -15.22.
  No unreported commission component is invented.
- Final observed broker positions: zero. Working orders: zero. Original stop
  status Canceled, fill volume zero. No orphan stop remains. No duplicate entry
  or close was submitted. No Leader order route was used.
- Exit execution slippage against a synchronized pre-wire quote is unavailable;
  a prior UI/approval snapshot is not relabeled as an execution-time benchmark.

**Operational entry, attached protection and separately authorized full close
were broker-confirmed. The software test is NOT marked COMPLETE.** Its strict
exit timestamp gate rejects the exit because the broker timestamp is approximately
1.116 seconds before the local durable close intent. A clock-domain discrepancy
is suspected; no arbitrary clock tolerance or fabricated timestamp was inserted.
The actual broker exit is the unique new opposing fill in the isolated Practice
history, but the existing automatic matcher still reports
FLAT_RECONCILIATION_PENDING. The test record remains unresolved, with both
automatic entry profiles paused. The existing production worker independently
marked its corresponding job Closed after flat-state cleanup; the controller did
not force-complete its separate test record. Do not repeat a close, clear the test,
enable strategies or declare automated acceptance merely because the account is
flat. Resolve the timestamp attribution with measured evidence and regression
coverage first. This is a real operational finding, not another proposed trade.

All live order operations used the existing Phase 10 workflow and separate
human approvals. Durable intent/event records remain in the local SQLite audit.
Sanitized, freshly queried order/trade history and final broker counts were saved
using the existing evidence writer to the ignored local artifact
`data/verification/phase11-broker-roundtrip-evidence.json`. It preserves both the
actual fills and the unresolved software state; it does not clear reservations.
No credentials or full account search response were exported. No trading worker
was restarted.

## Primary Sources

- [Topstep Practice accounts](https://help.topstep.com/en/articles/8284134-practice-account): provider account-management context; operator must inspect the exact account.
- [TopstepX platform and Auto OCO](https://help.topstep.com/en/articles/14434175-topstepx): account-specific Risk Settings and bracket distance guidance.
- [ProjectX account search](https://gateway.docs.projectx.com/docs/api-reference/account/search-accounts/): no category/bracket-mode discriminator documented.
- [ProjectX order/bracket placement](https://gateway.docs.projectx.com/docs/api-reference/order/order-place/): attached stop semantics and rejection with an order ID.
- [ProjectX order search](https://gateway.docs.projectx.com/docs/api-reference/order/order-search/), [trade search](https://gateway.docs.projectx.com/docs/api-reference/trade/trade-search/) and [status enums](https://gateway.docs.projectx.com/docs/realtime/): actual fill/fee/status evidence.
- [ProjectX full-position close](https://gateway.docs.projectx.com/docs/api-reference/positions/close-positions/): existing full-close route, not partial transport.
- [CME hours/holidays](https://www.cmegroup.com/trading-hours.html) and [Topstep trading hours](https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade): sources for actual calendar review; local conservative cutoffs retained.
