"""Shared watch settings; account execution permissions live in bot_controls."""
from contextlib import closing
from live_store import connect


def read_stop_minutes():
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS stop_settings (id INTEGER PRIMARY KEY, minutes INTEGER NOT NULL)")
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
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_settings (id INTEGER PRIMARY KEY, orb_minutes INTEGER NOT NULL)")
        row = conn.execute("SELECT orb_minutes FROM strategy_settings WHERE id=1").fetchone()
    return row[0] if row and row[0] in (5,15,30) else 15


def save_orb_minutes(minutes):
    if type(minutes) is not int or minutes not in (5,15,30):
        raise ValueError("Opening range must be 5, 15 or 30 minutes")
    with closing(connect()) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS strategy_settings (id INTEGER PRIMARY KEY, orb_minutes INTEGER NOT NULL)")
        conn.execute("INSERT OR REPLACE INTO strategy_settings VALUES (1,?)", (minutes,))
        conn.commit()
