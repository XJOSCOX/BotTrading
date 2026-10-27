"""Read-only strategy history hydration, independent of browser and execution."""
import logging
from threading import Event

from goxtrade.data.chart_history import backfill_history
from goxtrade.data.history_download import ReadOnlyHistory
from goxtrade.execution.contracts import contract_for_symbol


def recover_once(symbols, initialized, reader, *, lookback_hours=168):
    outcomes={}
    for symbol in symbols:
        contract=contract_for_symbol(symbol)
        if not contract:
            outcomes[symbol]="No active contract mapping"
            continue
        key=(symbol,contract)
        try:
            count=backfill_history(symbol,lookback_hours if key not in initialized else 2,reader=reader)
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
