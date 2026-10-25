"""Shared watch settings; account execution permissions live in bot_controls."""
from contextlib import closing
from goxtrade.data.live_store import connect
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
import json


def read_previous_day_box_config():
    from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_parameters'").fetchone():
            return PreviousDayBoxConfig()
        row = conn.execute("SELECT record FROM strategy_parameters WHERE strategy_id='previous_day_box'").fetchone()
    return PreviousDayBoxConfig.from_dict(json.loads(row[0])) if row else PreviousDayBoxConfig()


def save_previous_day_box_config(values):
    from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
    config = PreviousDayBoxConfig.from_dict(values)
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_parameters (strategy_id TEXT PRIMARY KEY,record TEXT NOT NULL)")
        conn.execute("INSERT INTO strategy_parameters VALUES (?,?) ON CONFLICT(strategy_id) DO UPDATE SET record=excluded.record", ("previous_day_box",json.dumps(config.to_dict())))
        conn.commit()
    return config


def read_vwap_ema_config():
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_parameters'").fetchone():
            return VwapEmaConfig()
        row = conn.execute("SELECT record FROM strategy_parameters WHERE strategy_id='vwap_ema_cross'").fetchone()
    return VwapEmaConfig.from_dict(json.loads(row[0])) if row else VwapEmaConfig()


def save_vwap_ema_config(values):
    config = VwapEmaConfig.from_dict(values)
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_parameters (strategy_id TEXT PRIMARY KEY, record TEXT NOT NULL)")
        conn.execute("INSERT INTO strategy_parameters VALUES (?,?) ON CONFLICT(strategy_id) DO UPDATE SET record=excluded.record",
                     ("vwap_ema_cross", json.dumps(config.to_dict())))
        conn.commit()
    return config


def read_stop_minutes():
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='stop_settings'").fetchone():
            return 5
        row = conn.execute("SELECT minutes FROM stop_settings WHERE id=1").fetchone()
    return row[0] if row and row[0] in (5,10,15) else 5


def save_stop_minutes(minutes):
    if type(minutes) is not int or minutes not in (5,10,15):
        raise ValueError("Stop timeframe must be 5, 10 or 15 minutes")
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS stop_settings (id INTEGER PRIMARY KEY, minutes INTEGER NOT NULL)")
        conn.execute("INSERT OR REPLACE INTO stop_settings VALUES (1,?)",(minutes,))
        conn.commit()


def read_orb_minutes():
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_settings'").fetchone():
            return 15
        row = conn.execute("SELECT orb_minutes FROM strategy_settings WHERE id=1").fetchone()
    return row[0] if row and row[0] in (5,15,30) else 15


def save_orb_minutes(minutes):
    if type(minutes) is not int or minutes not in (5,15,30):
        raise ValueError("Opening range must be 5, 15 or 30 minutes")
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_settings (id INTEGER PRIMARY KEY, orb_minutes INTEGER NOT NULL)")
        conn.execute("INSERT OR REPLACE INTO strategy_settings VALUES (1,?)", (minutes,))
        conn.commit()
