# Previous Day Box Reversal

Strategy ID: `previous_day_box`. Confirmation: completed 15-minute candles.
Reference: the most recent completed eligible trading session, for the same actual
contract. This is an experimental reversal hypothesis, not a guaranteed edge.
Strong trends can continue beyond PDH/PDL; zones do not imply a market must reverse.

## Development Base and Delivery

Remote branches were fetched on October 24, 2026. `origin/main` was `a0d7fbe`;
`origin/feature/vwap-ema-cross` and the source branch were `20ab748`.
The latter contains main plus the completed VWAP strategy and Phase 2 validation.
The new branch is `feature/previous-day-box`. `f85cfc4` preserves the existing
uncommitted React/FastAPI redesign, account maintenance and tested Control Center
work before strategy development. Nothing was reset or merged into main.
Core strategy/research integration is `17ea074`; native/legacy interface integration,
complete strategy visibility and GoXFinance palette are `794fd5a`. Final validation
and documentation commits follow. Use `git log --oneline
20ab748..feature/previous-day-box` for their exact IDs.

## Mathematics and Sessions

PDH and PDL are the high/low of the entire eligible previous session. Range is
PDH-PDL; midpoint is (PDH+PDL)/2. Default discount/buy zone ends at PDL+25% of range;
premium/sell zone begins at PDL+75%. Custom percentages must surround 50% without
overlap. They are research parameters, not optimized recommendations.

`pandas-market-calendars==5.5.0`, calendar `CME_Equity`, supplies trading-session
dates, holidays, early closes and positive-duration breaks. Futures reference
defaults to 17:00-16:00 Chicago. RTH uses 08:30-15:00, intersected with actual exchange
hours. Custom HH:MM windows are also intersected with exchange sessions. Timezone
is always America/Chicago; DST changes UTC boundaries rather than local clocks.
Sunday evening belongs to Monday. Friday remains the eligible reference across
the weekend; the algorithm never blindly subtracts one calendar day.

The last eligible session must have every expected finalized minute, with valid
OHLC and matching contract provenance. It does not substitute an older session if
the immediately previous eligible session is incomplete. Partial capture, duplicate
minutes, future availability timestamps, unknown calendar boundaries, mismatched
contracts and missing history produce WAIT with a reason. No price interpolation,
zero-volume invention or continuous-contract splicing is used.

Runtime keeps the first complete box snapshot for a contract/session/window/zone
definition in `previous_day_boxes`. Daily corrections cannot rewrite an existing
signal's levels. Historical backtesting constructs boxes only from bars already
available at that simulation step. Parameter comparisons use separate runs.

Calendar code is not a live exchange-status oracle. Review extraordinary closures,
product-specific changes and the pinned library before deployment. Broker Practice
also requires the existing fresh operator-reviewed CME calendar, which can only
restrict entry. Sources: [official CME schedules](https://www.cmegroup.com/trading-hours.html)
and [calendar library documentation](https://pandas-market-calendars.readthedocs.io/en/latest/usage.html).
No current provider-side schedule verification or market-open test is claimed.

## Confirmation and Location

States are Below PDL, Discount, Neutral, Premium and Above PDH. The default does not
buy below PDL or sell above PDH. An outside excursion must close back inside its
extreme before a reversal is eligible. `ignore` suppresses outside-excursion setups;
`breakout_research` records outside states but does not invent breakout entries.

Evaluation order is location/outside permission, completed candle, then confirmation
tests in wick/sweep/structure order, followed by entry geometry and filters:

- Wick: lower wick for long, upper for short; wick must be at least the body or one
  tick, and close must meet the configured candle-location fraction (default 50%).
  Body denominator is at least one tick for doji safety. Optional body ratio,
  wick/range, directional close and midpoint filters are independent.
- Sweep: at least the configured tick distance beyond PDH/PDL (or selected zone
  boundary), followed by a completed close back across it. Optional next-candle
  confirmation requires a close beyond the sweep candle's opposite extreme.
- Structure: a recent completed edge rejection/reclaim followed by a completed
  break of a confirmed minor pivot. A pivot requires the configured number of
  left and right bars before the final trigger; future bars cannot confirm it early.
- Combined: explicit AND of all three tests or OR of any of them. It never uses
  unfinished candles or anticipatory broker entries.

The default entry window is 90 seconds after confirmation. Maximum drift is eight
ticks from the confirmation close, and movement toward neutral is capped at five
percentage points of box range beyond the zone edge. These configurable caps still
apply to next-available-price simulations and execution revalidation. No deep-neutral
delayed entry is accepted merely because a historical candle touched an edge.

Live monitoring requires a contract trade no older than ten seconds by default.
Execution revalidates the original candle, contract, window, post-detection stop
breaches and executable price. A new setting never turns an expired setup into an
eligible historical-price order.

## Risk and Experimental Filters

Stops support rejection extreme plus buffer (default two ticks), prior box extreme,
recent completed swing extrema, ATR, fixed ticks and the existing buffered policy.
Targets support midpoint, opposite zone, opposite boundary, fixed RR or the existing
adaptive exit manager. Initial stop and target must remain on correct sides after
tick rounding. Actual fill geometry is checked; an invalid broker fill requests
closure through the existing reconciled, bot-owned-position workflow. Stops are
not widened to accommodate a price move or account loss limit.

Adaptive exits retain the platform's frozen management settings and can tighten
stops; the reference target is not an automatic exit in adaptive mode. Saving
parameters does not change open-position settings. Account loss locks remain separate
from strategy stop placement.

Optional filters default off: candle-ratio refinements, ATR bounds, relative actual
trade volume, EMA context, session VWAP position, minimum/maximum box size, prior
session direction and time restrictions. Cooldown and maximum entries per box default
to zero (no additional strategy-specific restriction); existing account restrictions
still apply. Optional effective RR requires an explicit cost estimate or acknowledged
zero-cost sensitivity. Research uses actual configured simulation costs. Additional
filters are not assumed to improve profitability.

## Lifecycle and Execution

Monitoring defaults on; forward paper and broker Practice default off. Leader is
prohibited by the registry and submission boundary, regardless of stored policy.
Practice requires separate strategy permission, Control Center selection, account
arming, reviewed calendar, fresh data and all existing account/broker protections.
No copier settings are changed. No account was armed and no broker orders were
submitted during implementation or validation.

Setup IDs include strategy, symbol, actual contract, reference session, box version,
confirmation candle, direction and method. A separate consumption key omits tunable
parameters, box version and method. Changing thresholds or confirmation mode cannot
reopen the same symbol/contract/session/candle/direction after restart. Both watch
alerts and broker intents have durable consumption records. Existing alert/history
tables are preserved. Signals retain box levels, confirmation, frozen parameters,
risk levels, detection/expiration, contract, method and filter results.

Practice claims enforce the frozen per-box entry budget and strategy cooldown in
the same transaction as intent creation. Existing loss locks, sizing, no-hedging,
exposure, reconciliation, session cutoff, emergency-close and protective-order guards
are still mandatory. Pausing new entries never stops existing exit management.

The existing runtime watches NQ/ES/YM references and executes their corresponding
MNQ/MES/MYM contracts with matching expiries. Direct mini and micro instruments are
supported by the pure engine, research and box-detail chart. This change does not
add six independent broker monitoring loops or allow simultaneous mini/micro orders.

## Research and Forward Paper

Use `run_backtest(..., strategy='previous_day_box', strategy_config=config,
simulation=SimulationConfig(...))`. Real studies require actual finalized,
timezone-aware, single-contract minute OHLCV and explicit fees. Entries fill at the
next available observed open plus adverse slippage, not at the historical sweep.
Stop/target collisions use stop first; gaps and structure exits use the next observed
open. Wrong-side fill geometry is rejected. Open end positions are not counted as
realized profits. Contract point/tick values come from the shared verified instrument
specifications. No backtest calls a broker order endpoint.

`chronological_splits` supports expanding walk-forward windows without using future
test P&L for parameter selection. `compare_variations` in
`goxtrade.research.previous_day_box_research` runs independent wick, sweep, structure,
combined, target, zone-width and RTH comparisons. The UI can request walk-forward
validation and shows saved run metrics, directional/session/monthly breakdowns,
monthly returns, decision reasons and sample/trade counts. Additional variants can
be tested by changing validated parameters and saving separate runs.

Forward paper uses the existing separate simulation state/trade tables, a new
strategy identity and actual subsequent micro trade observations. It cannot fill on
the detection tick. It freezes entry configuration, models adverse slippage and
explicit commission, persists consumption across restarts, and continues managing
an existing simulated position when new paper entries are disabled. Paper never
submits broker orders or enters actual-account P&L. Research, forward paper, broker
Practice and Leader populations remain separate in comparison utilities.

At development-time inspection, `strategy_historical_minutes` and
`strategy_trade_minutes` both contained zero rows. No real-performance study could
be run. Deterministic test fixtures and browser fixtures prove behavior only, not
profitability. Display-only legacy candles are not silently promoted into verified
contract-specific strategy data. Load verified bars through explicit history recovery
after ProjectX access is restored, or supply a real single-contract CSV to research.

## Interface and Operations

React: **Control Center > Previous Day Box** saves validated settings in grouped
sections. **Strategies > Previous Day Box** shows the reference date, session,
levels, zone, bias, confirmation, expiration, quote time, events and a 15-minute
chart. The chart includes PDH/PDL/midpoint, shaded zones, confirmed method markers
and the latest same-reference signal's stop/entry/target. Volume/RSI panes keep a
shared timeline, including whitespace indicator warmup bars, and retain zoom.
Earlier-session entry lines are not carried onto a different reference box.

The Streamlit fallback has the same engine/chart/research under its new strategy
tab; its advanced validated settings use JSON. The native Control Center uses
regular inputs and toggles. Parameters never arm an account.

Strategy watch now uses the registry rather than only worker-returned rows. All
seven strategies remain visible, including during startup/weekend closure, with
selection separate from monitoring freshness. Missing/stale worker records are
explicitly unavailable, not fabricated signals. New workers must load the updated
code before the new runtime adapter can evaluate. Existing workers were not killed,
restarted or armed to deploy this interface. Use the existing guarded maintenance
flow to restart workers when account exposure/provider access can be verified.

The interface was restarted independently and uses GoXFinance's actual charcoal,
neutral-gray and sage palette; semantic profit/loss colors remain unchanged.

## Validation and Remaining Work

The unit suite passed 350 tests with no failures, errors or skips, including final
rollover and self-confirmation guards. The eight
requested test modules cover session math/calendar/DST/coverage, zones, doji/wicks,
sweeps, structure/combined/next-candle confirmations, execution envelope and Leader
denial, expiry/contract/drift, deduplication, frozen boxes, causal simulations,
paper fills, settings isolation and frozen entry budgets/cooldowns.

TypeScript/build passed. Browser QA covers all eight pages at six screen sizes,
interface restart/reconnection, the real settings API against temporary SQLite,
all selected strategies remaining visible without monitor rows, box settings
round-trip, desktop/mobile chart pixels, shaded zones, markers and retained zoom.
Visual fixtures remain browser-only and are never saved as market history.

Pending validation: restore ProjectX access; review official product schedules and
calendar coverage; obtain complete same-contract prior-session and current-session
history; run meaningful real-data parameter/walk-forward comparisons with costs;
restart workers through guarded maintenance; observe fresh market-open monitoring;
only then consider explicit Practice permission and authorization. Leader support
requires a separately reviewed change and cannot be enabled by these settings.

Known limits: no order-book/queue or bid/ask execution model, no reconstructed
intrabar paths from OHLC, no synthetic rollover, strict coverage can suppress valid
real-world setups when capture is incomplete, and calendar/data revisions need
operator review. No guarantee of reversal, positive expectancy or successful fills.

## File Manifest

The native-workspace preservation checkpoint is separate from these feature changes.
New files after that checkpoint:

```text
goxtrade/strategies/previous_day_box.py
goxtrade/strategies/previous_day_box_config.py
goxtrade/strategies/previous_day_box_sessions.py
goxtrade/strategies/previous_day_box_runtime.py
goxtrade/research/previous_day_box_research.py
goxtrade/data/previous_box_view.py
goxtrade/ui/bot/previous_day_box_panel.py
web/src/pages/PreviousDayBox.tsx
tests/previous_day_box_fixtures.py
tests/test_previous_day_box.py
tests/test_previous_day_box_sessions.py
tests/test_previous_day_box_zones.py
tests/test_previous_day_box_wicks.py
tests/test_previous_day_box_sweeps.py
tests/test_previous_day_box_backtest.py
tests/test_previous_day_box_integration.py
tests/test_previous_day_box_safety.py
tests/test_previous_day_box_browser.py
docs/PREVIOUS_DAY_BOX.md
```

Modified files:

```text
goxtrade/strategies/strategy_catalog.py
goxtrade/strategies/strategy_settings.py
goxtrade/strategies/entry_confirmation.py
goxtrade/bot/signal_lifecycle.py
goxtrade/execution/practice_executor.py
goxtrade/research/backtest.py
goxtrade/research/forward_paper.py
goxtrade/api/app.py
goxtrade/api/state.py
goxtrade/ui/bot/page.py
goxtrade/ui/market/chart_component/index.html
web/src/Chart.tsx
web/src/pages/Controls.tsx
web/src/pages/Strategies.tsx
web/src/pages/Research.tsx
web/src/styles.css
tests/test_native_api.py
tests/test_native_controls_browser.py
requirements.txt
README.md
docs/BOT_OPERATIONS.md
docs/NATIVE_APP.md
```

Confirmed integration fixes include stale/missing worker rows hiding registered
strategies, the native research route incorrectly passing VWAP-only configuration
to legacy strategies, and chart-pane time-index drift when RSI warmup bars were
dropped. These fixes do not redefine the existing strategies.
## Optional Central Paper Exit Management

New opted-in paper entries may freeze a shared exit policy after the existing box
entry and portfolio risk checks. This does not alter box geometry, enable Leader,
resize active positions or replace existing frozen exits. Review MFE/MAE and
giveback as diagnostics, not guarantees. See
[Trade Management Engine](TRADE_MANAGEMENT_ENGINE.md).
