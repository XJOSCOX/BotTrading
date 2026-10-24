import pandas as pd


def minutes(closes=None, start="2026-10-01T22:00:00Z"):
    closes = closes if closes is not None else [100.] * 45 + [99., 103.]
    start = pd.Timestamp(start)
    rows = [dict(time=start+pd.Timedelta(minutes=i*3+j), open=close, high=close+.25,
                 low=close-.25, close=close, volume=1.)
            for i, close in enumerate(closes) for j in range(3)]
    frame = pd.DataFrame(rows)
    frame.attrs["contract_id"] = "TEST.CONTRACT"
    return frame


def partial(price, sequence, now, base=None):
    base = minutes([100.]*45+[99.]) if base is None else base
    row = dict(time=pd.Timestamp(now).floor("min"), open=99.75,
               high=max(99.75, price), low=min(99.75, price), close=price,
               volume=float(sequence), last_sequence=sequence, asof_time=pd.Timestamp(now).isoformat())
    result = pd.concat([base, pd.DataFrame([row])], ignore_index=True)
    result.attrs.update(base.attrs)
    return result
