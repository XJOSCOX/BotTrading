"""Deterministic correctness fixtures only, never market-performance evidence."""
import pandas as pd
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.strategies.previous_day_box_sessions import session_windows

NOW = pd.Timestamp("2026-10-23T15:00:00Z")
CONTRACT = "CON.F.US.ENQ.Z26"


def history(now=NOW, config=None, contract=CONTRACT, direction="LONG"):
    config = config or PreviousDayBoxConfig()
    windows = session_windows(now,config)
    current = next(row for row in windows if row["open"]<=now<row["close"])
    previous = [row for row in windows if row["close"]<=current["open"]][-1]
    times = []
    for begin,end in previous["segments"]: times.extend(pd.date_range(begin,end,freq="min",inclusive="left"))
    times.extend(pd.date_range(current["open"],now,freq="min",inclusive="left"))
    frame = pd.DataFrame(dict(time=times))
    for name,value in dict(open=150.,high=151.,low=149.,close=150.,volume=10.,complete=True).items(): frame[name]=value
    frame.loc[0,["high","low"]]=[200.,100.]
    bar = dict(open=116.,high=120.,low=101.,close=118.) if direction=="LONG" else dict(open=184.,high=199.,low=180.,close=182.)
    for name,value in bar.items(): frame.loc[frame["time"]>=now-pd.Timedelta(minutes=15),name]=value
    frame.attrs.update(contract_id=contract,provenance="Deterministic unit-test fixture, not actual market data")
    return frame


def candidate(**changes):
    from goxtrade.strategies.previous_day_box import evaluate_previous_day_box
    config = PreviousDayBoxConfig.from_dict(changes)
    result=evaluate_previous_day_box(history(config=config),118.,NOW,config,symbol="NQ=F",contract_id=CONTRACT,quote_time=NOW)[0]
    result["detection_sequence"]=0
    return result
