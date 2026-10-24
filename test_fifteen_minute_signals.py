import unittest
from unittest.mock import patch
import pandas as pd
import bot_monitor
from signal_candles import signal_candles
from continuation_strategies import evaluate_orb,evaluate_vwap,evaluate_ema_pullback
from test_continuation_strategies import bars,mirror


def expand(frame):
    rows = []
    start = frame.iloc[0]["time"]
    for i,row in frame.reset_index(drop=True).iterrows():
        for minute in range(15):
            rows.append({**row.to_dict(),"time":start+pd.Timedelta(minutes=i*15+minute),"volume":row["volume"]/15})
    return pd.DataFrame(rows)


class FifteenMinuteTests(unittest.TestCase):
    def test_partial_and_missing_minutes_do_not_make_candles(self):
        frame = expand(bars([100.,101.,999.]))
        now = frame.iloc[30]["time"]+pd.Timedelta(minutes=3)
        self.assertEqual(len(signal_candles(frame,now)),2)
        self.assertEqual(len(signal_candles(frame.drop(index=20),now)),1)
        self.assertEqual(signal_candles(frame,now).iloc[-1]["close"],101)

    def test_orb_requires_two_fifteen_minute_closes(self):
        frame = expand(bars([100.,102.,103.,104.]))
        now=frame.iloc[45]["time"]
        for data,price,direction in ((frame,104,"LONG"),(mirror(frame),96,"SHORT")):
            self.assertEqual(evaluate_orb(data,price,now,interval=15)["signal"],direction)
            self.assertEqual(evaluate_orb(data,price,now-pd.Timedelta(seconds=1),interval=15)["signal"],"WAIT")

    def test_ema_and_vwap_use_fifteen_minute_indicators(self):
        ema=bars([100+i*12/119 for i in range(120)]+[111.7,111.4,111.1,110.8,110.5,111.4,111.5])
        vwap=bars([100+i*10/69 for i in range(70)]+[109.,108.,108.],"2026-09-16T22:00Z")
        vwap.loc[71,["open","low","high"]]=[107.,105.,109.]
        for evaluate,fixture,price in ((evaluate_ema_pullback,ema,111.5),(evaluate_vwap,vwap,108.)):
            for data,quote,direction in ((fixture,price,"LONG"),(mirror(fixture),200-price,"SHORT")):
                frame=expand(data)
                now=frame.iloc[-15]["time"]+pd.Timedelta(seconds=20)
                result=evaluate(frame,quote,now,interval=15)
                self.assertEqual(result["signal"],direction)

    def test_monitor_all_strategies_label_and_gate_missing_current_bar(self):
        frame=expand(bars([100+i*.1 for i in range(70)]))
        now=frame.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        ticks=pd.DataFrame([dict(time=now,price=107.)])
        session=dict(time=now,is_open=True,name="Regular")
        with patch("signal_lifecycle.management_timeframe",return_value=5),patch.object(bot_monitor,"read_stop_minutes",return_value=5),patch.object(bot_monitor,"read_orb_minutes",return_value=15),patch.object(bot_monitor,"track_signal",side_effect=lambda s,t,c,i,a,b:c) as track:
            for strategy in bot_monitor.STRATEGIES:
                result=bot_monitor.evaluate_strategy_status("NQ=F",strategy,session,ticks,candles_1m=frame)
                self.assertEqual(result["timeframe"],"15 min")
                self.assertEqual(result["signal"]["signal_minutes"],15)
                bot_monitor.evaluate_strategy_status("NQ=F",strategy,session,ticks,candles_1m=frame.iloc[:-1])
                self.assertFalse(track.call_args.args[4])
