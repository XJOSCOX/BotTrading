"""Pure, causal completed-15m box reversal evaluation. No persistence or broker I/O."""
import hashlib
import json
import math

import pandas as pd

from goxtrade.market.instruments import instrument, round_tick, validate_contract_instrument
from goxtrade.strategies.adaptive_exit import MODE
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.strategies.previous_day_box_sessions import previous_box, zone, session_windows
from goxtrade.strategies.signal_candles import signal_candles
from goxtrade.strategies.stop_policy import buffered_signal


def setup_keys(signal):
    identity = ["previous_day_box",signal["symbol"],signal["source_contract"],signal["session_id"],
                signal["candle_time"],signal["direction"]]
    consumed = hashlib.sha256("|".join(identity).encode()).hexdigest()
    unique = hashlib.sha256("|".join(identity+[signal["confirmation_method"],signal["box"]["version"]]).encode()).hexdigest()
    return consumed,unique


def wick_metrics(bar):
    o,h,l,c = (float(bar[name]) for name in ("open","high","low","close"))
    if not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or not l<=min(o,c)<=max(o,c)<=h or h<=l:
        raise ValueError("Invalid or zero-range confirmation candle")
    body = abs(c-o)
    return dict(upper=h-max(o,c),lower=min(o,c)-l,body=body,span=h-l,location=(c-l)/(h-l))


def rejection(bar, direction, config, tick):
    m = wick_metrics(bar)
    long = direction == "LONG"
    wick = m["lower" if long else "upper"]
    # A doji's denominator is one tick; tiny bodies never produce infinite ratios.
    return (m["span"] >= config.min_candle_ticks*tick and wick>=max(m["body"],tick)
            and (not config.wick_body_enabled or wick/max(m["body"],tick)>=config.wick_body_ratio)
            and (not config.wick_range_enabled or wick/m["span"]>=config.wick_range_ratio)
            and (m["location"]>=config.close_location if long else m["location"]<=1-config.close_location)
            and (not config.directional_close or (bar["close"]>bar["open"] if long else bar["close"]<bar["open"]))
            and (not config.close_midpoint or (m["location"]>.5 if long else m["location"]<.5)))


def swept(bar, box, direction, config, tick):
    long = direction == "LONG"
    level = box["pdl" if long else "pdh"] if config.sweep_boundary == "extreme" else box["buy_upper" if long else "sell_lower"]
    distance = config.min_sweep_ticks*tick
    return (bar["low"] <= level-distance and bar["close"]>level) if long else (bar["high"]>=level+distance and bar["close"]<level)


def confirmed_swing(bars, long, lookback):
    """A pivot needs lookback bars on both sides, all before the trigger candle."""
    name = "high" if long else "low"
    values = bars[name].tolist()
    found = []
    for index in range(lookback,len(values)-lookback):
        neighbors = values[index-lookback:index]+values[index+1:index+lookback+1]
        if all(values[index]>v if long else values[index]<v for v in neighbors):
            found.append(values[index])
    return found[-1] if found else None


def risk_levels(direction, entry, trigger, bars, minutes, box, config, tick):
    long = direction == "LONG"
    sign = 1 if long else -1
    entry = round_tick(entry,tick,up=long)
    prev_close = bars["close"].shift()
    tr = pd.concat([bars["high"]-bars["low"],(bars["high"]-prev_close).abs(),(bars["low"]-prev_close).abs()],axis=1).max(axis=1)
    atr = float(tr.tail(config.atr_length).mean()) if len(bars)>=config.atr_length else None
    base = float(trigger["low" if long else "high"])
    if config.stop_method == "box": base = box["pdl" if long else "pdh"]
    elif config.stop_method == "swing": base = float(bars.tail(config.swing_lookback)["low" if long else "high"].agg("min" if long else "max"))
    elif config.stop_method == "atr":
        if atr is None: raise ValueError("ATR stop requires initialized completed candles")
        base = entry-sign*atr*config.atr_multiple
    elif config.stop_method == "fixed": base = entry-sign*config.fixed_stop_ticks*tick
    stop = round_tick(base-sign*config.stop_buffer_ticks*tick,tick,up=not long)
    if config.stop_method == "buffered":
        rows = [{**r,"time":r["time"].isoformat()} for r in minutes.to_dict("records")]
        buffered = buffered_signal(dict(signal=direction,entry=entry,stop=stop,target=entry+(entry-stop)*2,tick_size=tick),rows,config.management_minutes)
        if buffered["signal"] == "WAIT": raise ValueError(buffered["reason"])
        stop = buffered["stop"]
    target = {"midpoint":box["midpoint"],"opposite_zone":box["sell_lower" if long else "buy_upper"],
              "opposite_boundary":box["pdh" if long else "pdl"]}.get(config.target_method,entry+(entry-stop)*config.reward_risk)
    target = round_tick(target,tick,up=not long)
    if not (0<stop<entry<target if long else 0<target<entry<stop):
        raise ValueError("Invalid rounded stop, entry or target; setup rejected")
    return dict(entry=entry,stop=stop,initial_stop=stop,target=target,atr=atr,
                initial_risk_points=abs(entry-stop),actual_reward_risk=abs(target-entry)/abs(entry-stop),
                tick_size=tick,management_minutes=config.management_minutes,trail_start_r=config.trail_start_r,
                exit_mode=MODE if config.target_method=="adaptive" else "fixed",risk_config=config.to_dict())


def validate_entry(signal, price, now, contract_id=None):
    """Run again at submission/fill: do not move stops to accommodate slippage."""
    config = PreviousDayBoxConfig.from_dict(signal.get("config_snapshot"))
    if contract_id is not None and contract_id != signal.get("source_contract"):
        return "Box confirmation contract changed"
    now = pd.Timestamp(now).tz_convert("UTC")
    start = pd.to_datetime(signal.get("confirmed_at"),utc=True,errors="coerce")
    if pd.isna(start) or not 0 <= (now-start).total_seconds() < config.entry_window_seconds:
        return "Box confirmation expired or future-dated"
    if price is None or not math.isfinite(float(price)) or price<=0:
        return "Fresh executable price unavailable"
    long = signal.get("signal",signal.get("direction")) == "LONG"
    if not (signal["stop"]<price<signal["target"] if long else signal["target"]<price<signal["stop"]):
        return "Executable price invalidates original box stop or target"
    if (signal.get("_post_detection_low",price)<=signal["stop"] if long else signal.get("_post_detection_high",price)>=signal["stop"]):
        return "A post-detection trade invalidated the original box stop"
    if abs(price-signal["reference_entry"]) > config.max_entry_drift_ticks*signal["tick_size"]:
        return "Price moved too far from the confirmed entry"
    box = signal["box"]
    extension = box["range"]*config.max_zone_extension_percent/100
    if (price>box["buy_upper"]+extension if long else price<box["sell_lower"]-extension):
        return "Price moved too far into the neutral zone"
    if price<box["pdl"] if long else price>box["pdh"]:
        return "Outside-box price requires a completed reclaim"
    return None


def evaluate_previous_day_box(minutes, price, now, config=None, *, symbol="NQ=F", contract_id=None,
                              quote_time=None, historical=False, schedule=None, box_override=None):
    config = PreviousDayBoxConfig.from_dict(config)
    now = pd.Timestamp(now).tz_convert("UTC")
    result = dict(strategy="Previous Day Box Reversal",strategy_id="previous_day_box",signal="WAIT",direction=None,
                  reason="Waiting for a completed box confirmation",entry=None,stop=None,target=None,
                  signal_minutes=15,entry_mode="CONFIRMED",entry_policy="previous-box-v1",symbol=symbol,
                  source_contract=contract_id,config_snapshot=config.to_dict(),config_fingerprint=config.fingerprint,
                  detected_at=now.isoformat(),entry_window_seconds=config.entry_window_seconds,filter_results={})
    bars = pd.DataFrame()
    try:
        if not config.monitor_enabled: raise ValueError("Previous Day Box monitoring is disabled")
        if symbol not in config.enabled_symbols: raise ValueError("Symbol is disabled for box monitoring")
        if not contract_id: raise ValueError("Actual contract identity required")
        validate_contract_instrument(symbol,contract_id)
        if minutes.attrs.get("contract_id") != contract_id: raise ValueError("Contract-specific history mismatch")
        source = minutes.copy()
        source["time"] = pd.to_datetime(source["time"],utc=True)
        source = source.loc[source["time"]+pd.Timedelta(minutes=1)<=now]
        if "complete" in source: source = source.loc[source["complete"].eq(True)]
        if "asof_time" in source: source = source.loc[pd.to_datetime(source["asof_time"],utc=True)<=now]
        source.attrs.update(minutes.attrs)
        values=source[["open","high","low","close"]]
        if (not values.map(lambda value: math.isfinite(value) and value>0).all().all()
                or (source["high"]<source[["open","close","low"]].max(axis=1)).any()
                or (source["low"]>source[["open","close","high"]].min(axis=1)).any()):
            raise ValueError("Invalid contract OHLC history")
        if (config.volume_enabled or config.vwap_enabled) and not source["volume"].map(lambda value: math.isfinite(value) and value>=0).all():
            raise ValueError("Actual traded volume is missing or invalid")
        box = box_override or previous_box(source,now,config,contract_id,schedule)
        result.update(box=box,session_id=box["session_id"],zone=zone(price,box) if price is not None else "Unavailable")
        bars = signal_candles(source,now,15,strict=True)
        if bars.empty: raise ValueError("Need fully completed 15-minute confirmation candles")
        last = bars.iloc[-1]
        confirmed_at = last["time"]+pd.Timedelta(minutes=15)
        if not 0 <= (now-confirmed_at).total_seconds() < config.entry_window_seconds:
            raise ValueError("Latest completed confirmation candle is stale or expired")
        if not historical:
            stamp = pd.to_datetime(quote_time,utc=True,errors="coerce")
            if pd.isna(stamp) or not 0 <= (now-stamp).total_seconds()<=config.max_data_age_seconds:
                raise ValueError("Fresh contract trade required; feed is stale")
        if price is None or not math.isfinite(float(price)): raise ValueError("No current executable trade price")
        tick = instrument(symbol).tick_size
        if ((source[["open","high","low","close"]]/tick).sub((source[["open","high","low","close"]]/tick).round()).abs()>1e-6).any().any():
            raise ValueError("History prices violate the instrument tick grid")
        for direction in ("LONG","SHORT"):
            long = direction=="LONG"
            trigger = bars.iloc[-2] if config.next_candle_confirmation and len(bars)>1 else last
            if config.next_candle_confirmation and (len(bars)<2 or last["time"]-trigger["time"]!=pd.Timedelta(minutes=15)):
                continue
            near = trigger["low"]<=box["buy_upper"] if long else trigger["high"]>=box["sell_lower"]
            outside = trigger["low"]<box["pdl"] if long else trigger["high"]>box["pdh"]
            reclaim = swept(trigger,box,direction,config,tick)
            reclaimed_extreme = trigger["close"]>box["pdl"] if long else trigger["close"]<box["pdh"]
            if not near or (outside and (config.outside_mode!="reclaim" or not reclaimed_extreme)):
                continue
            wick = rejection(trigger,direction,config,tick)
            # Structure is an edge rejection on an earlier completed candle followed
            # by a break of a pivot whose right-hand bars preceded the trigger.
            prior = bars.iloc[:-1]
            swing = confirmed_swing(prior,long,config.swing_lookback)
            structure = False
            for _, earlier in prior.tail(config.swing_lookback*2+1).iterrows():
                edge = earlier["low"]<=box["buy_upper"] if long else earlier["high"]>=box["sell_lower"]
                if edge and (rejection(earlier,direction,config,tick) or swept(earlier,box,direction,config,tick)):
                    structure = swing is not None and (last["close"]>swing if long else last["close"]<swing)
            checks = dict(wick=bool(wick),sweep=bool(reclaim),structure=bool(structure))
            passed = (all(checks.values()) if config.combined_logic=="AND" else any(checks.values())) if config.confirmation=="combined" else checks[config.confirmation]
            if config.next_candle_confirmation:
                passed &= last["close"]>trigger["high"] if long else last["close"]<trigger["low"]
            if not passed: continue
            levels = risk_levels(direction,price,trigger,bars,source,box,config,tick)
            result.update(levels,signal=direction,direction=direction,reference_entry=float(last["close"]),
                          confirmed_at=confirmed_at.isoformat(),setup_time=last["time"].isoformat(),candle_time=last["time"].isoformat(),
                          expires_at=(confirmed_at+pd.Timedelta(seconds=config.entry_window_seconds)).isoformat(),
                          confirmation_candle={**last.to_dict(),"time":last["time"].isoformat()},confirmation_method=config.confirmation,
                          confirmation_results=checks)
            blocked = validate_entry(result,price,now,contract_id)
            if blocked: raise ValueError(blocked)
            filters = {}
            def check(name, enabled, condition):
                filters[name] = "passed" if condition else "failed" if enabled else "disabled"
                if not enabled: filters[name] = "disabled"
            check("min_box",config.min_box_enabled,box["range"]>=config.min_box_ticks*tick)
            check("max_box",config.max_box_enabled,box["range"]<=config.max_box_ticks*tick)
            atr = levels["atr"]
            check("atr",config.atr_filter_enabled,atr is not None and config.atr_min_ticks<=atr/tick<=config.atr_max_ticks)
            average = bars.iloc[:-1].tail(config.volume_lookback)["volume"].mean()
            check("volume",config.volume_enabled,len(bars)>config.volume_lookback and math.isfinite(average) and average>0 and last["volume"]>=average*config.volume_multiplier)
            ema = bars["close"].ewm(span=config.ema_length,adjust=False).mean().iloc[-1]
            check("ema",config.ema_enabled,len(bars)>=config.ema_length and ((price>ema) if long else (price<ema)))
            current_session = next((row for row in session_windows(now,config,schedule) if row["open"]<=now<row["close"]),None)
            active = source.loc[source["time"]>=current_session["open"]] if current_session else source.iloc[:0]
            volume = active["volume"].sum()
            vwap = ((active["high"]+active["low"]+active["close"])/3*active["volume"]).sum()/volume if volume>0 else None
            check("vwap",config.vwap_enabled,vwap is not None and ((price>vwap) if long else (price<vwap)))
            check("previous_direction",config.previous_direction_enabled,box["session_direction"]==direction)
            clock = now.tz_convert("America/Chicago").strftime("%H:%M")
            within = config.entry_open<=clock<config.entry_close if config.entry_open<config.entry_close else clock>=config.entry_open or clock<config.entry_close
            check("hours",config.time_filter_enabled,within)
            result["filter_results"] = filters
            failed = [name for name,value in filters.items() if value=="failed"]
            if failed: raise ValueError("Experimental filters failed: "+", ".join(failed))
            # Consumption identity deliberately excludes tunable parameters/box levels.
            result["consumption_key"],result["unique_setup_id"] = setup_keys(result)
            result["reason"] = result["trigger_detail"] = f"{direction} {config.confirmation} on completed 15m candle; prior {config.session} session {box['session_id']}; PDH {box['pdh']}, PDL {box['pdl']}, midpoint {box['midpoint']}."
            return result,bars
        raise ValueError("No qualifying edge-zone completed-candle confirmation; neutral/outside entries blocked")
    except (ValueError,KeyError,TypeError,ImportError) as error:
        result.update(signal="WAIT",direction=None,entry=None,stop=None,target=None,reason=str(error),trigger_detail=str(error))
        return result,bars
