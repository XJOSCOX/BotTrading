import unittest
import pandas as pd
from continuation_strategies import evaluate_orb, evaluate_vwap, evaluate_ema_pullback, session_vwap, futures_anchor


def bars(prices, start="2026-09-17T13:30:00Z"):
    frame = pd.DataFrame({"time":pd.date_range(start,periods=len(prices),freq="min"),"close":prices})
    frame["open"] = frame["close"].shift().fillna(frame["close"])
    frame["high"] = frame[["open","close"]].max(axis=1)+.1
    frame["low"] = frame[["open","close"]].min(axis=1)-.1
    frame["volume"] = 10.
    return frame


def mirror(frame):
    frame = frame.copy()
    old_high = frame["high"].copy()
    for key in ("open","close"):
        frame[key] = 200-frame[key]
    frame["high"],frame["low"] = 200-frame["low"],200-old_high
    return frame


class ContinuationTests(unittest.TestCase):
    def test_orb_all_windows_and_directions(self):
        for minutes in (5,15,30):
            frame = bars([100.]*minutes+[102.,103.,104.])
            now = frame.iloc[-1]["time"]+pd.Timedelta(seconds=20)
            for data,price,direction in ((frame,104,"LONG"),(mirror(frame),96,"SHORT")):
                result = evaluate_orb(data,price,now,.25,minutes)
                self.assertEqual(result["signal"],direction)
                self.assertEqual(result["orb_minutes"],minutes)
                self.assertIn("two completed closes",result["trigger_detail"])

    def test_orb_waits_for_completion_and_missing_opening_data(self):
        frame = bars([100.]*15+[102.,103.,104.])
        now = frame.iloc[-1]["time"]+pd.Timedelta(seconds=20)
        self.assertEqual(evaluate_orb(frame,104,now-pd.Timedelta(minutes=1))["signal"],"WAIT")
        self.assertIn("missing",evaluate_orb(frame.iloc[1:],104,now)["reason"])
        self.assertEqual(evaluate_orb(frame,104,now+pd.Timedelta(hours=7))["signal"],"WAIT")
        self.assertEqual(evaluate_orb(frame,104,now+pd.Timedelta(days=1))["signal"],"WAIT")

    def test_orb_winter_cash_open_uses_central(self):
        frame = bars([100.]*15+[102.,103.,104.],"2026-01-16T14:30:00Z")
        self.assertEqual(evaluate_orb(frame,104,frame.iloc[-1]["time"]+pd.Timedelta(seconds=20))["signal"],"LONG")

    def test_vwap_trade_volume_and_current_bar_exclusion(self):
        frame = bars([10.,20.,1000.],"2026-09-16T22:00:00Z")
        for key in ("open","high","low"):
            frame[key] = frame["close"]
        frame["volume"] = [1.,3.,100000.]
        calculated,error = session_vwap(frame,frame.iloc[-1]["time"]+pd.Timedelta(seconds=20))
        self.assertIsNone(error)
        self.assertEqual(calculated.iloc[-1]["vwap"],17.5)
        for invalid in (None,-1,float("inf")):
            bad = frame.copy()
            bad.loc[0,"volume"] = invalid
            self.assertIsNotNone(session_vwap(bad,frame.iloc[-1]["time"])[1])
        self.assertIsNotNone(session_vwap(frame.iloc[1:],frame.iloc[-1]["time"])[1])

    def test_vwap_anchor_does_not_reset_at_midnight(self):
        self.assertEqual(futures_anchor(pd.Timestamp("2026-09-17T06:00Z")),pd.Timestamp("2026-09-16T22:00Z"))
        self.assertEqual(futures_anchor(pd.Timestamp("2026-01-16T06:00Z")),pd.Timestamp("2026-01-15T23:00Z"))

    def test_vwap_rejection_both_sides(self):
        frame = bars([100+i*10/69 for i in range(70)]+[109.,108.,108.],"2026-09-16T22:00:00Z")
        frame.loc[71,["open","low","high"]] = [107.,105.,109.]
        now = frame.iloc[-1]["time"]+pd.Timedelta(seconds=20)
        for data,price,direction in ((frame,108,"LONG"),(mirror(frame),92,"SHORT")):
            result = evaluate_vwap(data,price,now)
            self.assertEqual(result["signal"],direction)
            self.assertIn("Rejection",result["trigger_detail"])

    def test_ema_pullback_and_rsi_cross_both_sides(self):
        frame = bars([100+i*12/119 for i in range(120)]+[111.7,111.4,111.1,110.8,110.5,111.4,111.5])
        now = frame.iloc[-1]["time"]+pd.Timedelta(seconds=20)
        for data,price,direction in ((frame,111.5,"LONG"),(mirror(frame),88.5,"SHORT")):
            result = evaluate_ema_pullback(data,price,now)
            self.assertEqual(result["signal"],direction)
            self.assertIn("RSI14",result["trigger_detail"])
            self.assertEqual(evaluate_ema_pullback(data.drop(index=120),price,now)["signal"],"WAIT")

    def test_forming_and_future_bars_cannot_confirm(self):
        frame = bars([100.]*15+[102.,103.,104.])
        now = frame.iloc[-1]["time"]+pd.Timedelta(seconds=20)
        expected = evaluate_orb(frame,104,now)
        modified = frame.copy()
        modified.loc[len(frame)-1,["open","high","low","close"]] = [1,9999,0,1]
        self.assertEqual(evaluate_orb(modified,104,now),expected)
        self.assertEqual(evaluate_orb(pd.concat([frame,bars([9999.],"2026-09-18T13:30Z")]),104,now),expected)

    def test_flat_ema_has_no_signal(self):
        frame = bars([100.]*80)
        self.assertEqual(evaluate_ema_pullback(frame,100,frame.iloc[-1]["time"])["signal"],"WAIT")

    def test_missing_live_price_waits(self):
        frame = bars([100.]*80)
        for evaluate in (evaluate_orb,evaluate_vwap,evaluate_ema_pullback):
            for price in (None,float("nan"),float("inf")):
                self.assertEqual(evaluate(frame,price,frame.iloc[-1]["time"])["signal"],"WAIT")
