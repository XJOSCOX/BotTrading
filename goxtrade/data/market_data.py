from functools import lru_cache

import pandas as pd
import yfinance as yf


@lru_cache(maxsize=128)
def fetch_history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    data = ticker.history(period=period, interval=interval, auto_adjust=False)
    if data.empty:
        return data

    data = data.reset_index()
    time_column = "Datetime" if "Datetime" in data.columns else "Date"
    data[time_column] = pd.to_datetime(data[time_column])
    return data.rename(columns={time_column: "Time"})


def clear_market_cache() -> None:
    fetch_history.cache_clear()

