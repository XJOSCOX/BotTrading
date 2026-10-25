"""Read-only box details and chart payload shared by React and Streamlit."""
from contextlib import closing
from datetime import datetime, timezone
import json

import pandas as pd

from goxtrade.data.live_store import connect
from goxtrade.data.strategy_history import load_strategy_minutes, latest_trade
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.market.chart_indicators import indicator_points
from goxtrade.strategies.previous_day_box import evaluate_previous_day_box
from goxtrade.strategies.strategy_settings import read_previous_day_box_config


def view(symbol, now=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    config = read_previous_day_box_config()
    contract = contract_for_symbol(symbol)
    source = load_strategy_minutes(symbol,contract,now,hours=24*16)
    tick = latest_trade(symbol,contract)
    candidate,bars = evaluate_previous_day_box(source,tick["price"] if tick else None,now,config,symbol=symbol,contract_id=contract,
                                              quote_time=tick["event_time"] if tick else None)
    shown = bars.loc[bars["time"]>=now-pd.Timedelta(hours=48)] if not bars.empty else bars
    points = indicator_points(shown,"15min") if not shown.empty else []
    events = []
    with closing(connect()) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='strategy_signal_events'").fetchone():
            for row in conn.execute("SELECT record FROM strategy_signal_events WHERE strategy_id='previous_day_box' AND symbol=? ORDER BY detected_at DESC LIMIT 100",(symbol,)):
                event = json.loads(row[0])
                if event.get("source_contract")==contract: events.append(event)
    markers = []
    for event in events:
        stamp = int(pd.Timestamp(event["candle_time"]).timestamp())
        if stamp in {point["time"] for point in points}:
            long = event["signal"]=="LONG"
            markers.append(dict(time=stamp,position="belowBar" if long else "aboveBar",shape="arrowUp" if long else "arrowDown",
                                color="#82d6ad" if long else "#efa3a3",text=event["confirmation_method"]+" confirmed"))
    box = candidate.get("box")
    levels = {name:box[name] for name in ("pdh","pdl","midpoint","buy_upper","sell_lower")} if box else {}
    signal = next((event for event in events if box and event.get("session_id")==box["session_id"]),candidate)
    levels.update({key:signal.get(key) for key in ("entry","stop","target")})
    return dict(points=points,box=box,signal=candidate,events=events,markers=sorted(markers,key=lambda r:r["time"]),levels=levels,
                quote_time=tick["event_time"] if tick else None,session_definition=config.session,timezone="America/Chicago",contract_id=contract,
                next_eligible_entry=candidate.get("expires_at"),last_entry=events[0]["detected_at"] if events else None)
