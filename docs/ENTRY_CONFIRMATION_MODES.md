# Legacy Entry Confirmation

Practice Control Center stores `entry_confirmation_mode` in the existing
account-scoped `bot_controls` record. Missing settings default to `strict`.
Other policy saves and application restarts preserve the selected mode.

- **Strict (15m + 5m + 1m):** the original completed 15-minute setup,
  completed 5-minute directional body and close-to-close momentum, and
  post-setup completed 1-minute breakout with strong close and live follow-through.
- **Standard (15m + 5m):** the same setup and completed 5-minute directional
  confirmation, without the additional 1-minute breakout requirement.

The completed 5-minute candle is the latest available completed candle, as in
Strict; it need not be the first candle after the setup. Incomplete source
minutes cannot complete a 5-minute candle.

This selector affects only Practice CRT, Reversal, ORB, VWAP Reclaim and EMA
Pullback. Leader always uses Strict. VWAP EMA Cross and Previous Day Box keep
their independent confirmation paths.

Fresh trades, history completeness, original setup invalidation, target-before-entry
checks, entry drift, expiration, broker protection, manager arbitration and risk
checks remain mandatory. Saving does not start or pause trading, clear signals,
reset cancellation history, or change open-position exits. Subsequent entry checks
use the saved mode, including the final preflight check.

New order attempts store `entry_confirmation_mode`; the final pre-submission
confirmation updates it to the mode actually used. Execution order history displays
the field. Older records remain unmodified and display no mode rather than inferring
an unrecorded value.
