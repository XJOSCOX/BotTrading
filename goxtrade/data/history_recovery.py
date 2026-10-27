"""Read-only strategy history hydration, independent of browser and execution."""
import logging
from contextlib import closing
from datetime import datetime, timezone
from threading import Event

import pandas as pd

from goxtrade.data.chart_history import backfill_history
from goxtrade.data.history_download import ReadOnlyHistory
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.data.live_store import connect
from goxtrade.data.historical_quality import expected_minutes


def older_history_missing(symbol, contract, hours, now=None):
    """A nonempty bootstrap does not prove coverage outside the refresh window."""
    end = pd.Timestamp(now or datetime.now(timezone.utc)).floor("min")
    start = end-pd.Timedelta(hours=hours)
    end = end-pd.Timedelta(hours=2)
    expected = expected_minutes(start, end)
    with closing(connect()) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_historical_minutes'").fetchone():
            return bool(len(expected))
        stamps = conn.execute("SELECT time FROM strategy_historical_minutes WHERE symbol=? AND contract_id=? AND time>=? AND time<?",
                              (symbol, contract, start.isoformat(), end.isoformat())).fetchall()
    present = pd.to_datetime([row[0] for row in stamps], utc=True)
    return bool(len(expected.difference(present)))


def recover_once(symbols, initialized, reader, *, lookback_hours=168):
    outcomes={}
    for symbol in symbols:
        contract=contract_for_symbol(symbol)
        if not contract:
            outcomes[symbol]="No active contract mapping"
            continue
        key=(symbol,contract)
        try:
            bootstrap = key not in initialized or older_history_missing(symbol, contract, lookback_hours)
            count=backfill_history(symbol,lookback_hours if bootstrap else 2,reader=reader)
            if count:
                initialized.add(key)
                outcomes[symbol]=dict(contract=contract,bars=count)
            else:
                outcomes[symbol]="Provider returned no completed candles; history remains unavailable"
        except Exception as error:
            outcomes[symbol]=f"History recovery unavailable ({type(error).__name__})"
            logging.warning("%s history recovery failed (%s); existing data retained",symbol,type(error).__name__)
    return outcomes


def run(symbols, stop=None, *, refresh_seconds=300, lookback_hours=168):
    if not 30<=refresh_seconds<=3600 or not 48<=lookback_hours<=384:
        raise ValueError("Invalid bounded history recovery settings")
    stop=stop or Event()
    initialized=set()
    reader=ReadOnlyHistory()
    while not stop.is_set():
        recover_once(symbols,initialized,reader,lookback_hours=lookback_hours)
        stop.wait(refresh_seconds)
