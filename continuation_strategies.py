"""Closed-minute strategies. No broker access or order placement."""
import math
import pandas as pd
from market_session import CENTRAL
from reversal_strategy import add_rsi


def completed(candles, now):
    frame = candles.copy()
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    return frame.loc[frame["time"] + pd.Timedelta(minutes=1) <= pd.Timestamp(now)].sort_values("time").drop_duplicates("time",keep="last").reset_index(drop=True)


def contiguous(frame):
    return not frame.empty and frame["time"].diff().iloc[1:].eq(pd.Timedelta(minutes=1)).all()


def valid_price(price):
    return price is not None and math.isfinite(price) and price > 0


def wait(reason, price, **fields):
    return dict(signal="WAIT", reason=reason, trigger_detail=reason, entry=None, stop=None, target=None,
                range_high=None, range_low=None, last_close=price, **fields)


def indicators(frame):
    frame = add_rsi(frame)
    frame["ema20"] = frame["close"].ewm(span=20,adjust=False,min_periods=20).mean()
    frame["ema50"] = frame["close"].ewm(span=50,adjust=False,min_periods=50).mean()
    previous = frame["close"].shift()
    tr = pd.concat([frame["high"]-frame["low"],(frame["high"]-previous).abs(),(frame["low"]-previous).abs()],axis=1).max(axis=1)
    frame["atr"] = tr.rolling(14,min_periods=14).mean()
    return frame


def candidate(base, direction, price, stop, detail, tick, target_distance=None):
    sign = 1 if direction == "LONG" else -1
    risk = (price-stop)*sign
    if not math.isfinite(risk) or risk <= 0:
        return {**base,"reason":"Live price already invalidated the confirmed setup."}
    stop = (math.floor(stop/tick) if sign == 1 else math.ceil(stop/tick))*tick
    distance = max(tick, target_distance if target_distance is not None else 2*abs(price-stop))
    target = (math.ceil((price+distance)/tick) if sign == 1 else math.floor((price-distance)/tick))*tick
    return {**base,"signal":direction,"entry":float(price),"stop":float(stop),"target":float(target),"reason":detail,"trigger_detail":detail}


def evaluate_orb(candles, price, now, tick=.25, minutes=15):
    if not valid_price(price):
        return wait("Waiting for a valid live price.",price,orb_minutes=minutes)
    if minutes not in (5,15,30):
        raise ValueError("Unsupported opening range")
    local = pd.Timestamp(now).tz_convert(CENTRAL)
    anchor = local.normalize()+pd.Timedelta(hours=8,minutes=30)
    end = anchor+pd.Timedelta(minutes=minutes)
    base = wait(f"Waiting for the {minutes}-minute cash opening range (08:30 CT).",price,orb_minutes=minutes)
    if local.weekday() >= 5 or not anchor <= local < local.normalize()+pd.Timedelta(hours=15):
        return {**base,"reason":"ORB entries are limited to 08:30-15:00 CT on weekdays."}
    bars = completed(candles,now)
    opening = bars.loc[(bars["time"] >= anchor) & (bars["time"] < end)]
    if local < end:
        return base
    if len(opening)!=minutes or not contiguous(opening) or opening.iloc[0]["time"]!=anchor:
        return {**base,"reason":"Opening-range minutes are missing; no ORB signal."}
    high,low = float(opening["high"].max()),float(opening["low"].min())
    base.update(range_high=high,range_low=low)
    recent = bars.tail(3)
    if len(recent)!=3 or not contiguous(recent) or recent.iloc[-2]["time"]<end or high<=low:
        return {**base,"reason":"Waiting for two completed breakout-confirmation minutes."}
    before,first,last = (recent.iloc[i] for i in range(3))
    detail = f"ORB {minutes}m, 08:30-{end:%H:%M} CT; range {low:,.2f}-{high:,.2f}; two completed closes {first['close']:,.2f}, {last['close']:,.2f}."
    if before["close"]<=high and first["close"]>=high+tick and last["close"]>=high+tick and price>high:
        return candidate(base,"LONG",price,min(high,first["low"],last["low"]),detail+" Confirmed upside breakout.",tick,high-low)
    if before["close"]>=low and first["close"]<=low-tick and last["close"]<=low-tick and price<low:
        return candidate(base,"SHORT",price,max(low,first["high"],last["high"]),detail+" Confirmed downside breakout.",tick,high-low)
    return {**base,"reason":"No new two-close opening-range breakout.","trigger_detail":detail}


def futures_anchor(now):
    local = pd.Timestamp(now).tz_convert(CENTRAL)
    date = local.date() if local.hour>=17 else (local-pd.Timedelta(days=1)).date()
    return pd.Timestamp(f"{date} 17:00",tz=CENTRAL)


def session_vwap(candles, now):
    anchor = futures_anchor(now)
    frame = completed(candles,now)
    frame = frame.loc[frame["time"]>=anchor].reset_index(drop=True)
    if frame.empty or frame.iloc[0]["time"]!=anchor or not contiguous(frame):
        return frame,"Full minute coverage since 17:00 CT is required for session VWAP."
    volume = pd.to_numeric(frame.get("volume",pd.Series(index=frame.index,dtype=float)),errors="coerce")
    if volume.isna().any() or (volume<0).any() or not volume.map(math.isfinite).all() or volume.sum()<=0:
        return frame,"Valid per-minute trade volume is required for VWAP."
    typical = (frame["high"]+frame["low"]+frame["close"])/3
    frame["vwap"] = (typical*volume).cumsum()/volume.cumsum().replace(0,float("nan"))
    return frame,None


def evaluate_vwap(candles, price, now, tick=.25):
    if not valid_price(price):
        return wait("Waiting for a valid live price.",price,vwap=None)
    frame,error = session_vwap(candles,now)
    base = wait(error or "Waiting for a VWAP retest aligned with the EMA20/50 trend.",price,vwap=None)
    if error or len(frame)<52:
        return base if error else {**base,"reason":"Need 52 session minutes for VWAP trend confirmation."}
    frame = indicators(frame)
    before,prior,last = (frame.iloc[i] for i in (-3,-2,-1))
    vwap = float(last["vwap"])
    base.update(vwap=vwap,range_low=float(last["low"]),range_high=float(last["high"]))
    tolerance = max(tick,float(last["atr"])*.15)
    touch = last["low"]<=vwap+tolerance and last["high"]>=vwap-tolerance
    up = last["ema20"]>last["ema50"] and last["ema50"]>prior["ema50"]
    down = last["ema20"]<last["ema50"] and last["ema50"]<prior["ema50"]
    long_cross = before["close"]<=before["vwap"] and prior["close"]>prior["vwap"]
    short_cross = before["close"]>=before["vwap"] and prior["close"]<prior["vwap"]
    detail = f"Session VWAP {vwap:,.2f} anchored 17:00 CT (HLC3 x trade volume); EMA20 {last['ema20']:,.2f}, EMA50 {last['ema50']:,.2f}; retest tolerance {tolerance:.2f}."
    base["trigger_detail"] = detail
    if touch and up and prior["close"]>prior["vwap"] and last["close"]>=vwap+tick and last["close"]>last["open"] and price>vwap:
        mode = "Reclaim" if long_cross else "Rejection from above"
        return candidate(base,"LONG",price,min(last["low"],prior["low"],vwap),detail+f" {mode}; bullish retest confirmed.",tick)
    if touch and down and prior["close"]<prior["vwap"] and last["close"]<=vwap-tick and last["close"]<last["open"] and price<vwap:
        mode = "Reclaim below" if short_cross else "Rejection from below"
        return candidate(base,"SHORT",price,max(last["high"],prior["high"],vwap),detail+f" {mode}; bearish retest confirmed.",tick)
    return base


def evaluate_ema_pullback(candles, price, now, tick=.25):
    if not valid_price(price):
        return wait("Waiting for a valid live price.",price,ema20=None,ema50=None,rsi=None)
    frame = completed(candles,now)
    base = wait("Need 60 contiguous completed minutes for EMA20/50 pullbacks.",price,ema20=None,ema50=None,rsi=None)
    if len(frame)<60 or not contiguous(frame.tail(60)):
        return base
    # Restart indicators after a data/session gap, never bridge missing minutes.
    gaps = frame["time"].diff().ne(pd.Timedelta(minutes=1))
    frame = indicators(frame.iloc[gaps[gaps].index[-1]:].reset_index(drop=True))
    last,prior = frame.iloc[-1],frame.iloc[-2]
    pullback = frame.iloc[-4:-1]
    base.update(ema20=float(last["ema20"]),ema50=float(last["ema50"]),rsi=None if pd.isna(last["rsi"]) else float(last["rsi"]),range_low=float(pullback["low"].min()),range_high=float(pullback["high"].max()))
    tolerance = max(tick,float(last["atr"])*.15)
    touched = any(((pullback["low"]<=pullback[key]+tolerance)&(pullback["high"]>=pullback[key]-tolerance)).any() for key in ("ema20","ema50"))
    detail = f"EMA20 {last['ema20']:,.2f}, EMA50 {last['ema50']:,.2f}; RSI14 {prior['rsi']:.2f} to {last['rsi']:.2f}; prior 3-minute EMA retest: {bool(touched)}; confirmation close {last['close']:,.2f}."
    base.update(reason="Waiting for EMA pullback plus RSI50 and candle momentum confirmation.",trigger_detail=detail)
    if touched and last["ema20"]>last["ema50"] and last["ema50"]>prior["ema50"] and prior["rsi"]<=50<last["rsi"] and last["close"]>max(prior["high"],last["open"],last["ema20"]) and price>last["ema20"]:
        return candidate(base,"LONG",price,min(last["low"],pullback["low"].min()),detail+" Bullish trend continuation.",tick)
    if touched and last["ema20"]<last["ema50"] and last["ema50"]<prior["ema50"] and prior["rsi"]>=50>last["rsi"] and last["close"]<min(prior["low"],last["open"],last["ema20"]) and price<last["ema20"]:
        return candidate(base,"SHORT",price,max(last["high"],pullback["high"].max()),detail+" Bearish trend continuation.",tick)
    return base
