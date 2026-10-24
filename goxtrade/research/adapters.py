"""Pure adapters for the existing strategy definitions; no account preflight emulation."""
import pandas as pd

from goxtrade.strategies.crt_strategy import evaluate_crt
from goxtrade.strategies.reversal_strategy import evaluate_reversal
from goxtrade.strategies.continuation_strategies import evaluate_orb, evaluate_vwap, evaluate_ema_pullback
from goxtrade.strategies.signal_candles import signal_candles
from goxtrade.strategies.stop_policy import buffered_signal
from goxtrade.strategies.adaptive_exit import MODE
from goxtrade.strategies.strategy_catalog import strategy_spec
from goxtrade.market.instruments import instrument


def legacy_candidate(minutes, price, now, symbol, strategy, settings=None):
    settings = settings or {}
    spec = strategy_spec(strategy)
    interval = spec.signal_minutes
    closed = signal_candles(minutes, now, interval)
    if closed.empty or closed.iloc[-1]["time"] != now.floor(f"{interval}min")-pd.Timedelta(minutes=interval):
        return dict(signal="WAIT")
    tick = instrument(symbol).tick_size
    live = pd.DataFrame([dict(time=now.floor(f"{interval}min"), open=price, high=price, low=price, close=price, volume=0.)])
    candles = pd.concat([closed, live], ignore_index=True)
    if spec.id == "crt":
        if len(closed) < 2 or closed.iloc[-1]["time"]-closed.iloc[-2]["time"] != pd.Timedelta(minutes=interval):
            return dict(signal="WAIT")
        signal = evaluate_crt(candles)
    elif spec.id == "reversal":
        gaps = closed["time"].diff().ne(pd.Timedelta(minutes=interval))
        signal = evaluate_reversal(pd.concat([closed.iloc[gaps[gaps].index[-1]:], live], ignore_index=True), interval=interval)[0]
    elif spec.id == "orb":
        signal = evaluate_orb(minutes, price, now, tick, settings.get("orb_minutes", 15), interval=interval)
    elif spec.id == "vwap_reclaim":
        signal = evaluate_vwap(minutes, price, now, tick, interval=interval)
    elif spec.id == "ema_pullback":
        signal = evaluate_ema_pullback(minutes, price, now, tick, interval=interval)
    else:
        raise ValueError("No historical adapter for this strategy")
    rows = [{**row, "time": row["time"].isoformat()} for row in minutes.to_dict("records")]
    signal.update(tick_size=tick, exit_mode=MODE, entry_mode="CONFIRMED", signal_minutes=interval)
    signal = buffered_signal(signal, rows, settings.get("management_minutes", 5))
    signal.update(setup_time=closed.iloc[-1]["time"].isoformat(),
                  unique_setup_id=f"{spec.id}|{symbol}|{closed.iloc[-1]['time'].isoformat()}|{interval}")
    return signal
