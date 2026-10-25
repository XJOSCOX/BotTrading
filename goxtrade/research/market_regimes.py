"""Prespecified descriptive labels from completed prior bars, never broker inputs."""
import pandas as pd


def classify(frame, entered_at):
    entered = pd.Timestamp(entered_at)
    times = pd.to_datetime(frame["time"],utc=True)
    known = frame.loc[times+pd.Timedelta(minutes=1) <= entered].tail(120)
    if len(known) < 60:
        return ["Insufficient regime warmup"]
    close = known["close"].astype(float)
    ranges = known["high"].astype(float)-known["low"].astype(float)
    atr = ranges.tail(14).mean()
    prior = ranges.iloc[:-14].mean()
    if not atr or not prior:
        return ["Unclassified flat observations"]
    spread = close.ewm(span=20,adjust=False).mean().iloc[-1]-close.ewm(span=50,adjust=False).mean().iloc[-1]
    labels = ["Trending up" if spread > .5*atr else "Trending down" if spread < -.5*atr else "Sideways / ranging"]
    labels.append("High volatility" if atr > 1.5*prior else "Low volatility" if atr < .67*prior else "Normal volatility")
    ct = entered.tz_convert("America/Chicago")
    minutes = ct.hour*60+ct.minute
    if 510 <= minutes < 540:
        labels.append("Opening-session expansion" if atr > prior else "Opening session")
    if not 510 <= minutes < 900 and labels[0] == "Sideways / ranging":
        labels.append("Overnight consolidation")
    return labels


def session(entered_at):
    ct = pd.Timestamp(entered_at).tz_convert("America/Chicago")
    minute = ct.hour*60+ct.minute
    return "Regular" if 510 <= minute < 900 else "Extended" if 900 <= minute < 960 else "Overnight"
