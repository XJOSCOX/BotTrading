# Trade Management Engine

## Delivery and Permissions

Phase 3 was verified with **404 tests passing in 54.018 seconds**, a clean worktree,
and its complete `0429744` integration. It was pushed to
`origin/feature/strategy-execution-manager` before Phase 4 edits. This branch,
`feature/trade-management-engine`, starts at that commit, includes Previous Day Box
and VWAP EMA Cross, and does not merge into main.

The new engine is **research/paper-only**. Its global opt-in defaults **off** and
its default policy is **baseline**. Existing positions without an explicit new
snapshot remain on their original state machines. No broker account settings,
credentials, arming, copier configuration or persistent $500 gate were changed.
No broker order/modify/cancel endpoint was invoked during development.

Read [FULL_SYSTEM_AUDIT.md](FULL_SYSTEM_AUDIT.md) for the full static per-file
inventory, manual critical-path findings, integration map and coverage limits.

Reviewable implementation commits: `d7c0084` (engine, recovery, research adapters)
and `ec1a61e` (shared interfaces/API and browser/Streamlit coverage).

## Verified Existing Behavior

`strategies/adaptive_exit.py`, `bot/signal_lifecycle.py`, `research/backtest.py`,
`research/forward_paper.py` and `execution/practice_executor.py` confirm:

- Adaptive reference targets do not force a close; fixed/breakeven targets do.
- Structure confirmation uses completed management candles, gap checks and a
  configured consecutive-break count. Buffered setups arm trailing at 1.5R;
  other frozen policies can use different thresholds.
- The broker entry builder attaches an original stop bracket, not a TP bracket.
- Software stop changes are not automatically amended at the broker. The original
  verified broker stop remains authoritative while software exits may request a
  full close. Broker reconciliation verifies exact observed fills/quantities.
- A price can retrace between a favorable extreme and completed-bar confirmation.
  This is an observed design characteristic, not proof that faster exits improve
  expectancy. Existing adaptive mode remains a prespecified comparison baseline.

Confirmed defect repaired: candidate risk metadata omitted `trail_buffer` and
`break_confirmations` (and original `stop_atr` context). Normalization now retains
them. This repairs newly frozen research ownership without rewriting historical
records or changing active broker orders. Regression tests cover the round-trip.

## Architecture

- `execution/profit_policy.py`: immutable validated exit-policy snapshots and ten
  prespecified experimental variations.
- `execution/trade_manager.py`: pure open/observe/propose/reconcile engine, no
  broker transport. It reuses original completed-candle adaptive management for
  baseline policy rather than changing the entry strategy.
- `execution/partial_exits.py`: explicit whole-contract partial ladder; never
  fractional or silently resized, and never increases quantity.
- `execution/trade_analytics.py`: observed MFE/MAE, marked and realized results,
  capture, giveback and diagnostic categories.
- `execution/position_protection.py`: verified request-shape adapter, permanently
  disabled broker transport, durable mock intent/reconciliation safety.
- `execution/profit_service.py`: shared research settings/read-only broker views
  and separate paper/comparison populations.
- `research/managed_positions.py`: adapters shared by portfolio and strategy paper;
  existing unsnapshotted positions remain legacy.
- `research/exit_policy_comparison.py`: one causal candidate tape, prespecified
  comparisons, chronological fixed-parameter validation.

Position lifecycle is protected/open -> monitoring/locked -> exit intent -> fill
reconciliation -> remainder monitoring or closed. A pending intent latches the
exit quantity; later observations cannot generate competing exits. Fill IDs are
deduplicated, quantities validated and unknown outcomes are never blindly retried.

## Frozen Policy and Settings

`profit_policy` is a separate SQLite table; it never writes account controls or
strategy execution permissions. The UI is shared in Practice and Leader views.
Saving settings only affects newly opted-in candidates/positions, not existing
positions or frozen pending entries. Exit snapshots have a stable fingerprint;
tampering is rejected. Existing policies are not implicitly migrated by restart.

Modes:

1. **Baseline:** preserve the original fixed, breakeven, trailing or adaptive
   owner rules and their management interval/buffer/break count.
2. **Fixed:** full exit at strategy target, explicit structural target, R multiple,
   configured points or whole ticks.
3. **Breakeven:** after the configured R milestone, move protection to entry plus
   an optional tick/cost buffer. Final target is independently configurable.
4. **Trailing:** favorable extreme with fixed ticks, completed ATR, completed
   structure or adaptive-style structure. A new stop must remain behind the
   currently observed market and can only tighten.
5. **Profit lock:** after a configured R milestone, protect a fraction of observed
   favorable movement. Default example threshold is 1.5R and retained fraction .5.
6. **Partial:** an explicit increasing list of (R milestone, whole quantity), then
   a trailing remainder. A one-contract position cannot partially exit. A ladder
   that would consume the entire remainder is blocked and reported, not resized.
7. **Hybrid:** optional breakeven, partial ladder, profit lock, trailing remainder
   and final target, configured independently.

New-policy candle management uses 5/10/15-minute bars. This does not globally
shorten legacy management. ATR uses 14 true ranges from 15 contiguous completed
management bars; structure requires a contiguous owned-bar window. Incomplete,
future/as-of-unavailable or duplicate observations cannot supply a trail.

No stop can move in the direction of greater risk. Structural entry stops are not
tightened to fit quantity. The Strategy Manager remains the authority for initial
sizing/costs, portfolio/group capacity and new-entry restrictions. After a partial
fill, portfolio quantity and remaining planned exposure are reduced; the original
trade quantity remains in episode analytics. Confidence never enlarges a position.

Breakeven is an estimate, not a guaranteed zero loss. Commissions, adverse fills,
gaps and an unavailable quote can still make an apparently protected trade lose.

## Profit and Giveback Definitions

For longs, MFE points = max(observed price)-actual entry fill, and MAE points =
actual entry fill-min(observed price). Shorts reverse the relationships. Extrema
are clamped at zero excursion and exclude observations after the final exit.
Price-excursion dollars use actual point value and **original filled quantity** so
partial exits do not silently rewrite excursion history.

The engine separately tracks remaining marked gross unrealized P&L, episode gross
P&L including partial realizations, net marked episode value with explicit fees,
an adverse-slippage liquidation estimate, realized fill P&L, estimated/modelled
slippage, holding time and current/maximum R.

Episode giveback compares maximum marked episode gross with current/final gross;
net giveback is separately recorded. Giveback percentage is undefined when there
was no positive marked peak. Captured R divides final net by original price risk.
Time from the last attained peak to final exit is recorded. For partial positions,
booked gross plus the remaining mark is used to avoid artificial giveback caused
solely by reducing quantity.

Diagnostics include reaching 1R/1.5R/2R then closing negative and an adaptive
reference target being touched without an automatic close. These labels are not
evidence that a different policy will improve out-of-sample results.

## Broker Capability Investigation and Blockers

Official references reviewed October 24, 2026:

- [Place an Order](https://gateway.docs.projectx.com/docs/api-reference/order/order-place/):
  TP and stop bracket objects use ticks/type fields; account bracket mode matters.
  Position Brackets can reject request brackets, even returning an order identity
  with rejection. A pure TP-building adapter is behind explicit flags and leaves
  the existing stop untouched. It also requires a reviewed signed offset and
  independently verified Auto OCO mode; no sender calls this adapter.
- [Modify an Order](https://gateway.docs.projectx.com/docs/api-reference/order/order-modify/):
  account/order identity and optional size/price fields are documented. Trailing
  price is an absolute level, not a tick distance. The engine sends none of these
  requests; schema existence is not proof of safe linked-order amendments.
- [Partially Close Positions](https://gateway.docs.projectx.com/docs/api-reference/positions/close-positions-partial/):
  account, contract and whole size are documented, including pending/rejected
  outcomes. Automatic resizing/cancellation of linked protective quantities was
  not established by these documents and is therefore not assumed.
- [Cancel an Order](https://gateway.docs.projectx.com/docs/api-reference/order/order-cancel/):
  cancellation has pending/rejection cases and account restrictions. Accepted
  cancellation alone is not proof of flat exposure or absence of residual orders.

The new broker transport always raises an execution-disabled error. There is no
UI switch that can activate it. Take-profit/stop amendment, partial-close and OCO
quantity semantics require a separately reviewed sandbox integration before any
real transport is introduced. The original stop bracket and emergency/full-close
path are preserved, and the new feature cannot change broker-account settings.

The durable mock exit ledger uses `BEGIN IMMEDIATE`, a unique active-exit index,
persisted intent before a hypothetical send, exact-account fresh-snapshot checks,
and reconciliation of remaining size/side and a linked stop of the correct size.
Missing protection or residual flat-account orders block safe completion. Timeout
or partial/unknown outcomes retain active intent. A repeated identical intent is
not resubmitted after restart. This is tested safety scaffolding, not an authorized
real-account order path.

## Historical Comparisons

Ten prespecified variants: original baseline; fixed 1R/1.5R/2R; breakeven after 1R;
ATR trail; structure trail; profit lock; first partial plus trail; hybrid.

All share the same observable entry-candidate tape, source contracts, periods,
portfolio risk policy and explicit cost assumptions. Different exit timing can
change which later candidates fit portfolio capacity; this is shown as portfolio
competition, not a guarantee of identical selected trades. No independent P&Ls are
added and no priority/policy is fitted from future evaluation outcomes.

New stops calculated at a completed bar apply only going forward. Old-stop/target
collisions use stop-first. OHLC cannot establish intrabar excursion order. If the
old stop is hit, no later bar extremes are credited as MFE; surviving-bar bounds
are labeled estimates. Profit triggers use modeled threshold prices with adverse
slippage. Structure exits wait for the next observed open. Missing data never
creates synthetic fills or a continuous contract rollover.

Outputs include standard net/win rate/profit factor/expectancy/drawdown/loss streak,
MFE/MAE, capture, giveback, holding time, and strategy/instrument/session breakdowns.
Chronological folds retain preceding warmup and fixed parameters; there is no
automatic winner selection. Empty genuine datasets are not replaced with fixtures.

## Forward Paper and Accounting

Existing strategy-level and portfolio paper reuse the same engine only for new
explicit snapshots. They remain separate ledgers. Original entry permissions,
fills, costs and portfolio risk constraints remain authoritative. Disabling new
entries does not stop owned exits. Late/stale/wrong-contract data cannot tighten
protection. The portfolio's compare-and-swap and original tick cursors preserve
restart/concurrent-worker deduplication.

Partial fills update remaining whole quantity and cash realization immediately.
Performance trade counts include one completed episode, not each partial as a
separate winning trade; partial fills remain nested for audit. No simulated fill
is labeled a broker fill. Existing strategy paper keeps original quantity metadata
and freezes its policy; new settings cannot resize or reconfigure it.

## Interface

Trade Management is available in the native sidebar and the legacy Streamlit
Strategies tab in both account views. It includes positions, shared exit-policy
settings, whole-contract partial ladder, software levels, giveback diagnostics and
separate exit-policy comparisons. Broker positions are read-only and retain their
original management; a reported stop is labeled with snapshot freshness rather
than silently treated as currently guaranteed protection.

## Readiness and Validation

Tests use deterministic fixtures, mock responses and temporary databases. Neither
broker account nor portfolio paper mode is activated by development or UI imports.
Exact final results and commits are in the completion report/branch history.

Validation on October 24, 2026:

- Full suite: **433 tests in 54.670 seconds, zero failures, errors or skips**. Commands:
  `python -m unittest discover`, `python -m compileall -q goxtrade scripts tests`.
- TypeScript and Vite production build pass; entry JS approximately 86 KB gzip.
- New native browser QA passes at 2560, 1440, 1280, 834, 390 and 320 pixels:
  both profiles, all four tabs, populated fixture positions/reviews, whole-contract
  partial settings, save/reload and draft retention on rejected save.
- Existing Strategy Manager and Control Center browser QA passes at the same six
  widths. Original Streamlit Trade Management rendering passes in both profiles.
- No production settings were used for test writes. Mock/temporary DB tests cover
  stale/foreign/reversed/oversized reconciliation, competing working orders,
  residual orders after failed cancellation and duplicate intent recovery.
- One sandbox-restricted supplemental run stalled in process inspection and was
  interrupted. Its unrestricted, broker-mocked rerun passed all 26 focused tests;
  final complete runs also passed. Existing dependency deprecation/bare-Streamlit
  warnings remain; deliberate failure-fixture logs are not production failures.

Historical partial milestones are rounded to the instrument grid. New protection
from a partial's bar cannot invent a trail-before-reversal intrabar ordering.
Portfolio scenario and chronological comparisons share the same selected exit
snapshot. Recorded slippage dollars are exit-fill deviation from the observed
mark; entry slippage is already embedded in the actual simulated entry basis,
not invented as an independently observed broker quote.

Actual strategy-history tables were empty before this work. Market-open data,
genuine portfolio performance, empirical superiority of any exit rule and real
linked-order behavior remain unverified. Next steps: restore/verify the provider,
capture complete same-contract histories, run costed chronological comparisons,
then deliberately opt into independent paper testing. Broker cutover remains
blocked until separately authorized and proven safe.
