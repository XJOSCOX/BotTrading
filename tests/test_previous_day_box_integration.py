from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd

from goxtrade.api import state
from goxtrade.bot.signal_lifecycle import track_signal
from goxtrade.data import live_store
from goxtrade.research.forward_paper import advance_paper
from goxtrade.strategies.previous_day_box_config import PreviousDayBoxConfig
from goxtrade.strategies.strategy_catalog import LEGACY_STRATEGIES, strategy_spec
from goxtrade.strategies.strategy_settings import read_previous_day_box_config,save_previous_day_box_config
from tests.previous_day_box_fixtures import NOW,CONTRACT,candidate


class BoxIntegrationTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        patcher=patch.object(live_store,"DB_PATH",Path(folder.name)/"box.db");patcher.start();self.addCleanup(patcher.stop)

    def test_registry_and_legacy_definitions_preserved(self):
        self.assertEqual(LEGACY_STRATEGIES,("CRT","Reversal","ORB","VWAP Reclaim","EMA Pullback"))
        self.assertEqual(strategy_spec("vwap_ema_cross").signal_minutes,3)
        self.assertEqual(strategy_spec("previous_day_box").execution_profiles,("practice",))

    def test_persisted_settings_do_not_arm_or_change_other_strategy(self):
        from goxtrade.strategies.strategy_settings import read_vwap_ema_config
        before=read_vwap_ema_config()
        save_previous_day_box_config(dict(buy_percent=20,sell_percent=80,stop_method="box"))
        self.assertEqual(read_previous_day_box_config().buy_percent,20)
        self.assertEqual(before,read_vwap_ema_config())
        with closing(live_store.connect()) as conn:
            tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("practice_control",tables);self.assertNotIn("leader_control",tables)

    def test_restart_and_config_change_deduplication(self):
        first=candidate()
        with closing(live_store.connect()) as conn:
            conn.execute("INSERT INTO live_ticks(symbol,contract_id,event_type,price,event_time,received_at) VALUES(?,?,?,?,?,?)",("NQ=F",CONTRACT,"trade",118,NOW.isoformat(),NOW.isoformat()))
            conn.commit()
        track_signal("NQ=F",first["strategy"],first,first["unique_setup_id"],True,[])
        changed=candidate(buy_percent=30,sell_percent=70)
        with closing(live_store.connect()) as conn:
            conn.execute("DELETE FROM signal_lifecycle")
            conn.commit()
        track_signal("NQ=F",changed["strategy"],changed,changed["unique_setup_id"],True,[])
        with closing(live_store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM bot_alert_history").fetchone()[0],1)

    def test_forward_paper_requires_later_real_tick_and_stays_separate(self):
        config=PreviousDayBoxConfig(paper_enabled=True,paper_commission_per_side=.5)
        signal=candidate(paper_enabled=True,paper_commission_per_side=.5)
        empty=pd.DataFrame(dict(time=pd.Series([],dtype="datetime64[ns, UTC]")))
        state,_=advance_paper({},signal,[],empty,"MNQ=F","CON.F.US.MNQ.Z26",config,NOW)
        self.assertIsNotNone(state["pending"]);self.assertIsNone(state["active"])
        tick=dict(id=1,price=118,event_time=(NOW+pd.Timedelta(seconds=1)).isoformat(),received_at=(NOW+pd.Timedelta(seconds=1)).isoformat())
        state,trades=advance_paper(state,signal,[tick],empty,"MNQ=F","CON.F.US.MNQ.Z26",config,NOW+pd.Timedelta(seconds=1))
        self.assertIsNotNone(state["active"]);self.assertEqual(trades,[])
        tick.update(id=2,price=151,event_time=(NOW+pd.Timedelta(seconds=2)).isoformat())
        state,trades=advance_paper(state,{},[tick],empty,"MNQ=F","CON.F.US.MNQ.Z26",replace(config,paper_enabled=False),NOW+pd.Timedelta(seconds=2))
        self.assertIsNone(state["active"])
        self.assertEqual(trades[0]["strategy_id"],"previous_day_box")
        self.assertEqual(trades[0]["test_type"],"forward_paper")
        with closing(live_store.connect()) as conn:
            self.assertFalse(conn.execute("SELECT 1 FROM sqlite_master WHERE name='practice_jobs'").fetchone())

    def test_runtime_adapter_persists_serializable_signal_and_frozen_box(self):
        from goxtrade.strategies.previous_day_box_runtime import evaluate_status
        from tests.previous_day_box_fixtures import history
        tick=dict(id=1,price=118,event_time=NOW.isoformat(),received_at=NOW.isoformat())
        with closing(live_store.connect()) as conn:
            conn.execute("INSERT INTO live_ticks(symbol,contract_id,event_type,price,event_time,received_at) VALUES(?,?,?,?,?,?)",("NQ=F",CONTRACT,"trade",118,NOW.isoformat(),NOW.isoformat()))
            conn.commit()
        with patch("goxtrade.strategies.previous_day_box_runtime.load_strategy_minutes",return_value=history()),patch("goxtrade.strategies.previous_day_box_runtime.latest_trade",return_value=tick):
            first=evaluate_status("NQ=F","Previous Day Box Reversal",dict(time=NOW,is_open=True,name="Regular"))
            second=evaluate_status("NQ=F","Previous Day Box Reversal",dict(time=NOW,is_open=True,name="Regular"))
        self.assertEqual(first["signal"]["signal"],"LONG")
        self.assertEqual(first["signal"]["unique_setup_id"],second["signal"]["unique_setup_id"])
        json.dumps(first,default=str)
        with closing(live_store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM strategy_signal_events").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT count(*) FROM previous_day_boxes").fetchone()[0],1)

    def test_broker_claim_honors_frozen_box_budget_and_cooldown(self):
        from goxtrade.execution import practice_executor as executor
        signal=candidate(max_entries_per_box=1)
        job={**signal,"alert_id":2,"state":"Intent","side":0,"quantity":1,"symbol":"MNQ","contract_id":"CON.F.US.MNQ.Z26"}
        old=dict(alert_id=1,state="Closed",strategy_id="previous_day_box",source_contract=CONTRACT,session_id=signal["session_id"],closed_confirmed_at=NOW.isoformat())
        with closing(executor.db()) as conn:
            conn.execute("INSERT INTO practice_jobs VALUES(?,?)",(1,json.dumps(old)));conn.commit()
        with patch.object(executor,"execution_block",return_value=None),patch.object(executor.time,"time",return_value=NOW.timestamp()),patch.object(executor.overnight_policy,"overnight",return_value=False):
            self.assertFalse(executor.claim(job))
            job["config_snapshot"]=PreviousDayBoxConfig(max_entries_per_box=0,cooldown_minutes=10).to_dict()
            self.assertFalse(executor.claim(job))
        with patch.object(executor,"execution_block",return_value=None),patch.object(executor.time,"time",return_value=NOW.timestamp()+601),patch.object(executor.overnight_policy,"overnight",return_value=False):
            self.assertTrue(executor.claim(job))

    def test_rollover_never_manages_old_signal_with_new_contract_bars(self):
        from goxtrade.strategies.previous_day_box_runtime import evaluate_status
        from tests.previous_day_box_fixtures import history
        frozen=candidate()
        with closing(live_store.connect()) as conn:
            conn.execute("CREATE TABLE signal_lifecycle(symbol TEXT,strategy TEXT,state TEXT,PRIMARY KEY(symbol,strategy))")
            conn.execute("INSERT INTO signal_lifecycle VALUES(?,?,?)",("NQ=F",frozen["strategy"],json.dumps(dict(active=frozen,cursor=0))))
            conn.commit()
        tick=dict(id=1,price=118,event_time=NOW.isoformat(),received_at=NOW.isoformat())
        with patch("goxtrade.strategies.previous_day_box_runtime.contract_for_symbol",return_value="CON.F.US.ENQ.H27"),patch("goxtrade.strategies.previous_day_box_runtime.load_strategy_minutes",return_value=history()) as load,patch("goxtrade.strategies.previous_day_box_runtime.latest_trade",return_value=tick),patch("goxtrade.strategies.previous_day_box_runtime.track_signal",side_effect=lambda symbol,strategy,candidate,event,allow,bars:candidate) as track,patch("goxtrade.research.forward_paper.forward_once") as paper:
            result=evaluate_status("NQ=F",frozen["strategy"],dict(time=NOW,is_open=True,name="Regular"))
        self.assertEqual(load.call_args.args[1],CONTRACT)
        self.assertFalse(track.call_args.args[4])
        self.assertEqual(paper.call_args.args[1]["signal"],"WAIT")
        self.assertIsNotNone(result["rollover_review"])
