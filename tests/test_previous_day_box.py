import unittest
from dataclasses import replace
import pandas as pd
from goxtrade.strategies.previous_day_box import evaluate_previous_day_box, validate_entry
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from tests.previous_day_box_fixtures import NOW, CONTRACT, history, candidate


class PreviousDayBoxTests(unittest.TestCase):
    def test_long_short_and_frozen_envelope(self):
        for direction,price in (("LONG",118),("SHORT",182)):
            result,_=evaluate_previous_day_box(history(direction=direction),price,NOW,contract_id=CONTRACT,quote_time=NOW)
            self.assertEqual(result["signal"],direction,result["reason"])
            self.assertEqual(result["signal_minutes"],15)
            self.assertEqual(len(result["unique_setup_id"]),64)
            self.assertEqual(result["config_snapshot"]["stop_method"],"rejection")

    def test_incomplete_live_candle_does_not_repaint(self):
        frame=history();before=candidate()
        future=pd.DataFrame([dict(time=NOW,open=118,high=500,low=1,close=400,volume=1000,complete=False)])
        after=pd.concat([frame,future],ignore_index=True);after.attrs.update(frame.attrs)
        result,_=evaluate_previous_day_box(after,118,NOW,contract_id=CONTRACT,quote_time=NOW)
        self.assertEqual(before["unique_setup_id"],result["unique_setup_id"])

    def test_neutral_stale_expired_and_disabled_wait(self):
        for changes,price,quote in (({},150,NOW),({},118,NOW-pd.Timedelta(seconds=11)),(dict(monitor_enabled=False),118,NOW)):
            result,_=evaluate_previous_day_box(history(),price,NOW,changes,contract_id=CONTRACT,quote_time=quote)
            self.assertEqual(result["signal"],"WAIT",result)
        signal=candidate()
        self.assertIn("expired",validate_entry(signal,118,NOW+pd.Timedelta(seconds=90)))
        self.assertIsNotNone(validate_entry(signal,130,NOW))

    def test_all_stop_and_target_modes_valid(self):
        for stop in ("rejection","box","swing","atr","fixed","buffered"):
            for target in ("midpoint","opposite_zone","opposite_boundary","rr","adaptive"):
                signal=candidate(stop_method=stop,target_method=target)
                self.assertEqual(signal["signal"],"LONG",(stop,target,signal["reason"]))
                self.assertLess(signal["stop"],signal["entry"])
                self.assertGreater(signal["target"],signal["entry"])

    def test_config_change_does_not_reset_consumption_identity(self):
        first=candidate();second=candidate(buy_percent=30,sell_percent=70,reward_risk=3)
        self.assertEqual(first["consumption_key"],second["consumption_key"])
        self.assertNotEqual(first["unique_setup_id"],second["unique_setup_id"])
        third=candidate(confirmation="combined")
        self.assertEqual(first["consumption_key"],third["consumption_key"])

    def test_optional_filter_failure_explained(self):
        signal=candidate(min_box_enabled=True,min_box_ticks=1000)
        self.assertEqual(signal["signal"],"WAIT")
        self.assertIn("min_box",signal["reason"])

    def test_structure_break_uses_only_already_confirmed_pivots(self):
        frame=history()
        shapes=[(120,122,110,121),(122,124,121,123),(119,121,118,120),(121,123,120,122),(125,128,124,126)]
        for index,shape in enumerate(shapes):
            start=NOW-pd.Timedelta(minutes=75-index*15)
            frame.loc[(frame["time"]>=start)&(frame["time"]<start+pd.Timedelta(minutes=15)),["open","high","low","close"]]=shape
        signal,_=evaluate_previous_day_box(frame,126,NOW,dict(confirmation="structure",swing_lookback=1),contract_id=CONTRACT,quote_time=NOW)
        self.assertEqual(signal["signal"],"LONG",signal["reason"])
        self.assertTrue(signal["confirmation_results"]["structure"])

    def test_combined_and_or_and_next_candle_sweep_confirmation(self):
        self.assertEqual(candidate(confirmation="combined",combined_logic="OR")["signal"],"LONG")
        self.assertEqual(candidate(confirmation="combined",combined_logic="AND")["signal"],"WAIT")
        frame=history()
        for start,shape in ((NOW-pd.Timedelta(minutes=30),(102,104,99,103)),(NOW-pd.Timedelta(minutes=15),(104,106,103,105))):
            frame.loc[(frame["time"]>=start)&(frame["time"]<start+pd.Timedelta(minutes=15)),["open","high","low","close"]]=shape
        signal,_=evaluate_previous_day_box(frame,105,NOW,dict(confirmation="sweep",next_candle_confirmation=True),contract_id=CONTRACT,quote_time=NOW)
        self.assertEqual(signal["signal"],"LONG",signal["reason"])

    def test_y_m_whole_ticks_and_micro_specifications(self):
        for symbol,contract in (("YM=F","CON.F.US.YM.Z26"),("MYM=F","CON.F.US.MYM.Z26"),("MNQ=F","CON.F.US.MNQ.Z26"),("MES=F","CON.F.US.MES.Z26")):
            frame=history(contract=contract)
            signal,_=evaluate_previous_day_box(frame,118,NOW,dict(enabled_symbols=[symbol]),symbol=symbol,contract_id=contract,quote_time=NOW)
            self.assertEqual(signal["signal"],"LONG",signal["reason"])
            if symbol.startswith(("YM","MYM")): self.assertEqual(signal["stop"]%1,0)
