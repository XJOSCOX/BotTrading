from __future__ import annotations

import json
from strategy_catalog import STRATEGIES
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
BOT_STATE_PATH = DATA_DIR / "bot_state.json"

DEFAULT_BOT_STATE = {
    "running": False,
    "strategy": "CRT",
    "strategies": ["CRT"],
    "symbol": "",
    "symbols": [],
    "timeframe": "15min",
    "mode": "Watch",
    "quantity": 1,
}


def load_bot_state() -> dict:
    if not BOT_STATE_PATH.exists():
        return DEFAULT_BOT_STATE.copy()
    try:
        saved = json.loads(BOT_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return DEFAULT_BOT_STATE.copy()
    state = DEFAULT_BOT_STATE.copy()
    state.update({key: saved.get(key, value) for key, value in DEFAULT_BOT_STATE.items()})
    state["strategies"] = saved.get("strategies") or [state["strategy"]]
    state['symbols'] = saved.get('symbols') or ([state['symbol']] if state['symbol'] else [])
    return state


def save_bot_state(state: dict) -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    next_state = DEFAULT_BOT_STATE.copy()
    next_state.update({key: state.get(key, value) for key, value in DEFAULT_BOT_STATE.items()})
    BOT_STATE_PATH.write_text(json.dumps(next_state, indent=2), encoding="utf-8")
    return next_state


def start_bot(symbol: str | list[str], strategy: str | list[str], quantity: int, mode: str = "Watch") -> dict:
    symbols = [symbol] if isinstance(symbol, str) else list(dict.fromkeys(symbol))
    if not symbols:
        raise ValueError('Select at least one symbol')
    symbol = symbols[0]
    strategies = [strategy] if isinstance(strategy, str) else list(dict.fromkeys(strategy))
    if not strategies or any(item not in STRATEGIES for item in strategies):
        raise ValueError("Select at least one supported strategy")
    strategy = strategies[0]
    timeframe = "15min" if strategy == "CRT" else "1min"
    return save_bot_state(
        {
            "running": True,
            "strategy": strategy,
            "strategies": strategies,
            "symbol": symbol,
            "symbols": symbols,
            "timeframe": timeframe,
            "mode": mode,
            "quantity": quantity,
        }
    )


def stop_bot() -> dict:
    state = load_bot_state()
    state["running"] = False
    return save_bot_state(state)
