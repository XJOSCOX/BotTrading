import unittest
from unittest.mock import patch
import pandas as pd
from goxtrade.research.backtest import run_backtest, SimulationConfig, fill_validation, chronological_splits
from goxtrade.research.previous_day_box_research import compare_variations
from goxtrade.execution import projectx_client
from tests.previous_day_box_fixtures import NOW, CONTRACT, history


def dataset():
    frame=history()
    later=pd.DataFrame([dict(time=NOW+pd.Timedelta(minutes=i),open=118.,high=151.,low=117.,close=150.,volume=10.,complete=True) for i in range(3)])
    result=pd.concat([frame,later],ignore_index=True);result.attrs.update(frame.attrs)
    return result


class BoxBacktestTests(unittest.TestCase):
    def test_causal_next_observed_open_with_explicit_costs(self):
        with patch.object(projectx_client,"post",side_effect=AssertionError("No broker orders")):
            result=run_backtest(dataset(),"NQ",CONTRACT,"previous_day_box",simulation=SimulationConfig(commission_per_side=.5),trade_start=NOW)
        self.assertEqual(len(result["trades"]),1,result["decisions"])
        trade=result["trades"][0]
        self.assertEqual(trade["entry_time"],NOW.isoformat())
        self.assertEqual(trade["entry"],118.25)
        self.assertEqual(trade["exit"],149.75)
        self.assertEqual(trade["costs"],1)
        self.assertEqual(result["test_type"],"historical_backtest")
        self.assertIn("direction",result["breakdown"])

    def test_future_candles_cannot_change_reference_or_entry(self):
        first=run_backtest(dataset(),"NQ",CONTRACT,"previous_day_box",simulation=SimulationConfig(commission_per_side=.5),trade_start=NOW)
        changed=dataset();changed.loc[changed["time"]>NOW,"high"]=500
        second=run_backtest(changed,"NQ",CONTRACT,"previous_day_box",simulation=SimulationConfig(commission_per_side=.5),trade_start=NOW)
        self.assertEqual(first["trades"][0]["unique_setup_id"],second["trades"][0]["unique_setup_id"])
        self.assertEqual(first["trades"][0]["entry"],second["trades"][0]["entry"])

    def test_ambiguous_ohlc_stop_first_and_wrong_fill_geometry(self):
        frame=dataset();frame.loc[frame["time"]==NOW,"low"]=90
        result=run_backtest(frame,"NQ",CONTRACT,"previous_day_box",simulation=SimulationConfig(commission_per_side=.5),trade_start=NOW)
        self.assertEqual(result["trades"][0]["reason"],"Stop first / ambiguous OHLC")
        self.assertFalse(fill_validation(dict(signal="LONG",stop=100,target=150),151,"MNQ",SimulationConfig(commission_per_side=.5))["valid"])

    def test_missing_prior_history_no_fabricated_trades(self):
        frame=dataset().tail(18);frame.attrs["contract_id"]=CONTRACT
        result=run_backtest(frame,"NQ",CONTRACT,"previous_day_box",simulation=SimulationConfig(commission_per_side=.5),trade_start=NOW)
        self.assertEqual(result["trades"],[])

    def test_reproducible_dataset_hash_and_walk_forward(self):
        options=dict(strategy="previous_day_box",simulation=SimulationConfig(commission_per_side=.5),trade_start=NOW)
        first=run_backtest(dataset(),"NQ",CONTRACT,**options)
        second=run_backtest(dataset(),"NQ",CONTRACT,**options)
        self.assertEqual(first["dataset_hash"],second["dataset_hash"])
        self.assertEqual(first["trades"],second["trades"])
        folds=chronological_splits(dataset(),"NQ",CONTRACT,**options)
        self.assertEqual(len(folds),1)
        self.assertLess(pd.Timestamp(folds[0]["in_sample"]["end"]),pd.Timestamp(folds[0]["out_of_sample"]["end"]))

    def test_variants_are_independent_validated_configs(self):
        with patch("goxtrade.research.previous_day_box_research.run_backtest",return_value={}) as run:
            values=compare_variations(dataset(),"NQ",CONTRACT,SimulationConfig(commission_per_side=.5))
        self.assertEqual(len(values),11)
        self.assertEqual(run.call_count,11)
        self.assertEqual(run.call_args_list[-1].args[4].session,"rth")
