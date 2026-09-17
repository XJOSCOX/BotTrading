# Bot operations

## Execution

- Practice and the allowlisted Trading Combine leader use separate, fixed-account worker processes configured locally in `execution_target.py`. No follower routing is performed by this app.
- Leader defaults: 3 MNQ / 3 MES, MYM disabled. Enable MYM trading and Save leader settings explicitly opts into MYM with a selected quantity of 1-4. Disabling blocks new MYM entries without stopping exit management. Starting its monitor leaves entries paused; trading requires the explicit Start control and account/copier confirmations.
- Topstep copier configuration must be verified by the user. The app cannot verify copying or guarantee follower exits. Loss locks apply separately to each account, not the combined copier group.
- Orders, fills, controls, broker health and loss-lock state are account-isolated. Enabled execution or unresolved jobs on the other account block activation. Account-view selectors never arm execution.
- Monitor remains watch-only for all three indices and both strategies. Controls affect new Practice entries, not management of existing positions.
- MYM additionally requires its existing explicit activation flag. Default execution remains MNQ/MES.
- The persistent $500 account-loss lock and maximum four contracts per symbol remain in force.
- Up to three bot-owned micro positions, one per MNQ/MES/MYM. When flat, the first entry uses the selected size (1-4); with exposure open, new entries on other symbols are capped at one contract each. No additions on the same symbol, no automatic size increases, and no automatic reversal. The opposite-direction exposure guard and account-wide cooldown after any confirmed close remain in force.
- Additional entries require every existing position to reconcile to a bot job with matching quantity/direction and a linked protective stop. Unowned exposure, pending/uncertain entries, closing positions, or unrecognized orders block additional entries. Claims are serialized and the rule is checked again immediately before submission. Exit management continues across all bot positions, even when another job is pending review.
- Emergency close first pauses entries. The worker requests a close only for an identified bot-owned position. It does not retry an uncertain close, cancel unrelated orders, or flatten unowned positions. Flat confirmation requires no positions, orders, or unresolved jobs. Manual review may be required.
- Signal quotes and monitor timestamps must be at most 10 seconds old, and signals at most 15 seconds old. These conditions are rechecked after broker preflight. Stale data blocks new entries; broker backup stops remain in place.
- Protection requires a linked stop with matching parent entry, contract, direction, and size. The existing missing-stop emergency exit remains in force.
- Broker reconciliation continues while paused. A worker heartbeat alone is not evidence of flat exposure.
- Temporary transport errors and HTTP 401/408/429/5xx reconnect with a 3-30 second backoff, preserving the Run/Pause selection. Entries require successful reconciliation and all usual checks. Manual pause, loss locks, rejected or uncertain submissions are not automatically cleared. Non-transient errors still pause entries.

## Audit and notifications

New events persist in `bot_events`, with consecutive duplicate events suppressed per topic. The inbox is in-app only and survives navigation and restarts. No email, SMS, push, webhook, or external recipient is configured.

Trade review combines existing order-state records and new signal/decision events. Signal trail changes are software exit levels, not broker-stop amendments. Fill observation delay measures when the worker observed a fill, not the exchange's exact execution latency. Historical audit details cannot be reconstructed where they were never recorded.

## Additional monitored strategies

New setups use the shared Stop & trailing candles setting (5 minutes by default; 5/10/15 available). Initial stops use the more conservative of strategy invalidation and the last three completed management candles' swing, plus 0.5 ATR(14), with at least one ATR of distance. Fifteen contiguous completed management candles are required; missing buckets block a new setup. Trailing and two-confirmation structure exits use the same frozen timeframe. Price crossing a protective stop is still checked tick-by-tick. Existing signals without a saved timeframe retain their original one-minute management; settings never widen their stops. Wider initial stops increase dollar risk at unchanged quantity. The separate account loss lock is unchanged.

The monitor evaluates CRT, Reversal, ORB, VWAP Reclaim and EMA Pullback for NQ, ES and YM. New strategies are not automatically selected for account orders. Enable them separately in Leader settings or Practice execution controls. Existing account selections, micro sizing, exposure checks, cooldowns and the account loss lock still apply.

- ORB: shared opening-range setting of 5, 15 (default), or 30 minutes from 08:30 CT. Requires complete opening-range data, then two consecutive completed one-minute closes at least one tick beyond the range following a close inside that boundary. Entries are limited to weekdays before 15:00 CT, subject to the existing market/session gate. Range width provides a reference target.
- VWAP Reclaim: HLC3 weighted by actual per-minute trade volume, anchored at 17:00 CT. Requires complete minute coverage from the anchor and at least 52 completed session minutes. EMA20/50 alignment and EMA50 slope must agree. A completed candle must retest VWAP within max(one tick, 0.15 ATR), close away from it with a directional body, and follow a close on the same side. A preceding cross identifies a reclaim; otherwise this is rejection. Missing session data or invalid volume yields WAIT.
- EMA Pullback: at least 60 consecutive completed minutes. EMA20/50 alignment and EMA50 slope establish direction. One of the previous three candles must touch EMA20 or EMA50 within max(one tick, 0.15 ATR). RSI14 must cross 50 in the trend direction, with the confirmation candle closing beyond the previous high/low and EMA20, and a directional body.

Signals use completed candles and a fresh live price; forming candles cannot confirm entries. Stops start beyond the setup's candle/range invalidation and use the existing ATR buffer and adaptive exit manager. VWAP/EMA reference targets are twice the initial unbuffered risk; reference targets do not force closure. These are deterministic initial rules, not evidence of profitability. Replay currently supports CRT and Reversal only.

Method references: [VWAP](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/) and [EMA](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/ema).

## Replay lab

Replay reads already-saved complete minute candles. It does not call the broker, mutate live signals, or apply changes to execution settings. Saved comparisons live in `bot_replays`.

- Baseline: existing buffered stop and three-bar/two-break/1.5R management.
- CRT candidate: five-bar/two-break/2R management.
- Reversal candidate: three-bar/one-break/1R management.
- Optional candidate session filtering and oversized one-minute candle/ATR filtering.
- Configurable costs, slippage per side, and micro quantity; five-minute replay cooldown.
- One symbol and strategy per run, not an account-level portfolio simulation.
- Entries expose the next candle open only; subsequent candle ranges are not used for entry decisions. Stop gaps fill at the worse of the open and stop, with configured adverse slippage. Trail updates occur after the bar closes and never loosen the stop.
- Intrabar ordering cannot be recovered from OHLC. Stops use conservative ordering. Open-at-end positions are excluded from closed results. Historical bars and live-tick-derived candles can differ. Missing historical data is not fabricated.

Candidates and filters are research-only. No promotion control is provided. The first saved CRT comparison did not justify replacing the existing runtime exits.

## Verification

`python -m unittest discover`

`python test_bot_workspace_browser.py` tests navigation and the replay flow headlessly; it does not press execution controls.

`python test_leader_browser.py` checks leader sizing, disabled Start and account views without placing orders.
