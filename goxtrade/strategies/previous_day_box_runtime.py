"""Watch adapter. Uses contract-specific persisted history, never provider calls."""
from contextlib import closing
import json

import pandas as pd

from goxtrade.bot import strategy_events
from goxtrade.bot.signal_lifecycle import track_signal
from goxtrade.data.live_store import connect
from goxtrade.data.strategy_history import load_strategy_minutes, latest_trade
from goxtrade.execution.contracts import contract_for_symbol
from goxtrade.market.market_session import session_signal
from goxtrade.strategies.previous_day_box import evaluate_previous_day_box
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.strategies.strategy_settings import read_previous_day_box_config


def evaluate_status(symbol, strategy, session, allow_new=True):
    error = None
    try:
        config = read_previous_day_box_config()
    except (ValueError,TypeError,KeyError) as failure:
        config = PreviousDayBoxConfig(monitor_enabled=False)
        error = str(failure)
    now = pd.Timestamp(session["time"])
    contract = contract_for_symbol(symbol)
    rolled = False
    with closing(connect()) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='signal_lifecycle'").fetchone():
            row=conn.execute("SELECT state FROM signal_lifecycle WHERE symbol=? AND strategy=?",(symbol,strategy)).fetchone()
            active=(json.loads(row[0]).get("active") or {}) if row else {}
            if active.get("source_contract") and active["source_contract"]!=contract:
                contract=active["source_contract"]
                rolled=True
                allow_new=False
    minutes = load_strategy_minutes(symbol,contract,now,hours=24*16)
    tick = latest_trade(symbol,contract)
    fresh = tick and all(pd.notna(stamp:=pd.to_datetime(tick[name],utc=True,errors="coerce")) and 0<=(now-stamp).total_seconds()<=config.max_data_age_seconds for name in ("event_time","received_at"))
    candidate,bars = evaluate_previous_day_box(minutes,tick["price"] if tick else None,now,config,symbol=symbol,contract_id=contract,
                                               quote_time=tick["event_time"] if fresh else None)
    if error: candidate["reason"] = "Invalid box settings: "+error
    box = candidate.get("box")
    if box:
        # Freeze the first complete snapshot of this reference box. No daily revision
        # can rewrite an existing live signal or its original risk parameters.
        key = "|".join((symbol,contract,config.session,config.custom_open,config.custom_close,str(config.buy_percent),str(config.sell_percent),box["session_id"]))
        with closing(connect()) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS previous_day_boxes(identity TEXT PRIMARY KEY,record TEXT NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO previous_day_boxes VALUES(?,?)",(key,json.dumps(box)))
            frozen = json.loads(conn.execute("SELECT record FROM previous_day_boxes WHERE identity=?",(key,)).fetchone()[0])
            conn.commit()
        if frozen != box:
            candidate,bars = evaluate_previous_day_box(minutes,tick["price"] if tick else None,now,config,symbol=symbol,contract_id=contract,
                                                       quote_time=tick["event_time"] if fresh else None,box_override=frozen)
    candidate["detection_sequence"] = tick["id"] if tick else None
    candidate["trigger_detail"] = candidate["reason"]
    event = candidate.get("consumption_key")
    identity = "previous_day_box|"+symbol+"|"+str(contract)
    previous = strategy_events.observation(identity)
    updated = dict(previous)
    if event: updated.update(last_event=event,last_signal_at=candidate["detected_at"])
    stored = strategy_events.persist(identity,previous,updated,candidate)
    if stored is None:
        candidate.update(signal="WAIT",reason="Concurrent box observation advanced; retry on next snapshot")
        allow_new = False
    else: candidate = stored
    management = minutes.loc[minutes["time"]+pd.Timedelta(minutes=1)<=now]
    if "complete" in management: management = management.loc[management["complete"].eq(True)]
    rows = [{**row,"time":row["time"].isoformat(),"closed_at":(row["time"]+pd.Timedelta(minutes=1)).isoformat()} for row in management.to_dict("records")]
    signal = track_signal(symbol,strategy,candidate,candidate.get("unique_setup_id"),allow_new and config.monitor_enabled and bool(fresh) and session["is_open"],rows)
    signal = session_signal(signal,session)
    from goxtrade.research.forward_paper import forward_once
    paper = forward_once(symbol,{**candidate,"signal":"WAIT","unique_setup_id":None,"consumption_key":None} if rolled else candidate,config,now)
    if config.notify_wait and candidate["signal"]=="WAIT":
        from goxtrade.bot.bot_audit import emit
        emit("box-wait:"+symbol,"Previous Day Box waiting",candidate["reason"],notify=True)
    return dict(signal=signal,timeframe="15 min",focus_label="Previous day box",
                focus_value=f"{box['pdl']:,.2f} - {box['pdh']:,.2f}" if box else "Unavailable",
                box=box,indicator_snapshot=candidate,monitor_enabled=config.monitor_enabled,forward_paper=paper,candles=bars,
                rollover_review="Managing original contract; new entries wait for prior signal to close" if rolled else None)
