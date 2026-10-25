from contextlib import closing
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import pandas as pd
from goxtrade.data import live_store,lab_store
from goxtrade.replay import replay_clock, replay_store as store,replay_session as replay,replay_engine as engine
from goxtrade.replay.replay_adapter import import_ticks
from goxtrade.research.portfolio_backtest import run_portfolio_backtest
from goxtrade.execution.execution_policy import ExecutionPolicy
from goxtrade.execution.profit_policy import ProfitPolicy
from tests.test_validation_lab import metadata,CONTRACT
from tests.test_portfolio_backtest import minutes,signals


class ReplayTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.path=Path(directory.name)/"live.db"
        replay.loaded.cache_clear()
        for mock in (patch.object(live_store,"DB_PATH",self.path),patch("goxtrade.execution.projectx_client.post",side_effect=AssertionError("Broker transport forbidden")),patch("goxtrade.execution.projectx_client.login",side_effect=AssertionError("No ProjectX required"))):
            mock.start();self.addCleanup(mock.stop)
        self.frame=minutes(6)
        self.frame.loc[3,["high","close"]]=[125.,110.]
        self.meta={**metadata(),"start":self.frame.iloc[0].time.isoformat(),"end":(self.frame.iloc[-1].time+pd.Timedelta(minutes=1)).isoformat()}
        self.dataset=lab_store.save_dataset(self.frame,self.meta)
        self.request=dict(datasets=[self.dataset["id"]],strategies=["crt"],start=self.meta["start"],end=self.meta["end"],
            execution=dict(commission_per_side=.5,slippage_ticks=1,cooldown_minutes=0),exit_policy=dict(enabled=True,mode="fixed",target_method="rr",target_r=1))

    def source(self,known,prices,contracts,now,policy,**kw):
        kw.pop("configurations",None)
        return signals(known,prices,contracts,now,policy,**kw)

    def finish(self,identifier):
        for _ in range(20):
            result=replay.action(identifier,dict(action="step"))
            if result["status"]=="complete":return store.get(identifier)
        self.fail("Replay failed to complete")

    def test_clock_speeds_and_validation(self):
        self.assertEqual(replay_clock.due(60,1),1)
        self.assertEqual(replay_clock.due(1,60),1)
        self.assertEqual(replay_clock.due(0,"maximum"),25)
        for bad in (True,4,100,-1):
            with self.assertRaises(ValueError):replay_clock.speed(bad)

    def test_shared_kernel_exact_minute_accounting_and_causal_prices(self):
        with patch("goxtrade.research.validation_lab.candidates_at",side_effect=self.source):
            created=replay.create(self.request)
            result=self.finish(created["id"])
            baseline=run_portfolio_backtest([("MNQ",CONTRACT,self.frame)],ExecutionPolicy.from_dict(result["request"]["execution"]),
                candidate_source=self.source,profit_policy=ProfitPolicy.from_dict(result["request"]["exit_policy"]))
        self.assertEqual(result["state"],json.loads(json.dumps(baseline["state"])))
        self.assertEqual(result["next_index"],6)
        self.assertTrue(result["state"]["trades"])
        self.assertEqual(result["state"]["trades"][0]["entry_time"],"2026-10-22T15:02:00+00:00")
        self.assertEqual(engine.account(result)["balance"],50000+baseline["state"]["realized"])
        self.assertFalse(self.path.exists(),"Replay must not create the actual account DB")

    def test_pause_restore_restart_and_optimistic_fencing(self):
        with patch("goxtrade.research.validation_lab.candidates_at",side_effect=self.source):
            created=replay.create(self.request)
            identifier=created["id"]
            replay.action(identifier,dict(action="step"));replay.action(identifier,dict(action="pause"))
            before=store.get(identifier)
            replay.loaded.cache_clear()
            self.assertEqual(replay.detail(identifier)["next_index"],1)
            final=self.finish(identifier)
            stale=copy.deepcopy(before)
            with self.assertRaises(ValueError):store.save(stale)
            new=replay.action(identifier,dict(action="restart"))
            self.assertNotEqual(new["id"],identifier)
            self.assertEqual(new["next_index"],0)
            self.assertEqual(store.get(identifier)["state"],final["state"])
        with self.assertRaises(ValueError):replay.detail("100001")

    def test_speed_never_changes_decisions_maximum_playback(self):
        with patch("goxtrade.research.validation_lab.candidates_at",side_effect=self.source):
            expected=self.finish(replay.create(self.request)["id"])
            other=replay.create(self.request)
            replay.action(other["id"],dict(action="speed",speed="maximum"))
            replay.action(other["id"],dict(action="play"))
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                final=store.get(other["id"])
                if final["status"]=="complete":break
                time.sleep(.05)
            self.assertEqual(final["status"],"complete")
            self.assertEqual(final["state"],expected["state"])

    def test_versions_integrity_and_gap_fail_closed(self):
        created=replay.create(self.request)
        with patch.object(engine,"code_identity",return_value={**created["code"],"content_hash":"changed"}):
            with self.assertRaisesRegex(ValueError,"code version"):replay.action(created["id"],dict(action="step"))
        with closing(lab_store.connect()) as conn:
            conn.execute("UPDATE lab_bars SET close=close+0.25 WHERE dataset=?",(self.dataset["id"],));conn.commit()
        replay.loaded.cache_clear()
        with self.assertRaisesRegex(ValueError,"integrity"):replay.action(created["id"],dict(action="step"))

    def test_chart_never_reveals_future_and_seven_original_adapters(self):
        request={**self.request,"strategies":["crt","reversal","orb","vwap_reclaim","ema_pullback","vwap_ema_cross","previous_day_box"]}
        # Canonical catalog spells IDs; the existing parser is authoritative.
        from goxtrade.strategies.strategy_catalog import SPECS
        request["strategies"]=[s.id for s in SPECS]
        created=replay.create(request)
        self.assertFalse(replay.chart(created["id"],"MNQ")["bars"])
        result=replay.action(created["id"],dict(action="step"))
        bars=replay.chart(created["id"],"MNQ")["bars"]
        self.assertEqual(len(bars),1)
        self.assertTrue(all(pd.Timestamp(b["time"])+pd.Timedelta(minutes=1)<=pd.Timestamp(result["clock"]) for b in bars))
        result=replay.action(created["id"],dict(action="step"))
        self.assertEqual({w["strategy_id"] for w in result["waits"]},{s.id for s in SPECS})

    def ticks(self):
        rows=[]
        for index,row in self.frame.iterrows():
            for offset,value in enumerate((row.open,row.high,row.low,row.close)):
                rows.append(dict(sequence=len(rows)+1,time=(row.time+pd.Timedelta(seconds=offset*10)).isoformat(),price=value,volume=2.5,contract_id=CONTRACT))
        return pd.DataFrame(rows)

    def test_actual_tick_step_and_minute_reconciliation(self):
        pack=import_ticks(dict(dataset=self.dataset["id"],source="TEST FIXTURE ONLY",csv=self.ticks().to_csv(index=False),complete_recording=True))
        created=replay.create({**self.request,"ticks":pack["id"]})
        one=replay.action(created["id"],dict(action="step"))
        self.assertEqual(one["next_index"],1)
        self.assertFalse(replay.chart(created["id"],"MNQ")["bars"])
        four=replay.action(created["id"],dict(action="candle"))
        deadline=time.monotonic()+10
        while four["status"]=="playing" and time.monotonic()<deadline:
            time.sleep(.05);four=replay.detail(created["id"])
        self.assertEqual(four["next_index"],4)
        replay.loaded.cache_clear()
        five=replay.action(created["id"],dict(action="step"))
        self.assertEqual(five["next_index"],5)
        self.assertEqual(len(replay.chart(created["id"],"MNQ")["bars"]),1)
        changed=self.ticks();changed.loc[0,"contract_id"]="CON.F.US.MNQ.H27"
        with self.assertRaises(ValueError):import_ticks(dict(dataset=self.dataset["id"],source="TEST",csv=changed.to_csv(index=False),complete_recording=True))
        changed=self.ticks();changed.loc[0,"volume"]=99
        with self.assertRaisesRegex(ValueError,"reconcile"):import_ticks(dict(dataset=self.dataset["id"],source="TEST",csv=changed.to_csv(index=False),complete_recording=True))

    def test_no_gaps_no_realtime_fabrication_and_empty_state(self):
        with self.assertRaises(ValueError):replay.create({**self.request,"account_id":100001})
        with self.assertRaises(ValueError):replay.create({**self.request,"strategies":["vwap_ema_cross"],"configurations":{"vwap_ema_cross":{"entry_mode":"REALTIME"}}})
        partial=lab_store.save_dataset(self.frame.iloc[:-1],self.meta)
        with self.assertRaises(ValueError):replay.create({**self.request,"datasets":[partial["id"]]})
        self.assertFalse(replay.overview()["sessions"])

    def test_all_exit_policies_incremental_parity_and_partial_analytics(self):
        from goxtrade.execution.profit_policy import comparison_policies
        from goxtrade.research.portfolio_backtest import prepare_portfolio
        from dataclasses import replace
        datasets=[("MNQ",CONTRACT,self.frame)]
        prepared=prepare_portfolio(datasets)
        with patch("goxtrade.research.validation_lab.candidates_at",side_effect=self.source):
            for name,profit in comparison_policies().items():
                created=replay.create({**self.request,"execution":{**self.request["execution"],"requested_quantity":2,"max_contracts":2},"exit_policy":profit.to_dict()})
                frozen=store.get(created["id"])
                for _ in range(6):frozen=engine.step(frozen,datasets,prepared=prepared)
                baseline=run_portfolio_backtest(datasets,ExecutionPolicy.from_dict(frozen["request"]["execution"]),candidate_source=self.source,profit_policy=profit)
                self.assertEqual(json.loads(json.dumps(frozen["state"])),json.loads(json.dumps(baseline["state"])),name)
                for trade in frozen["state"]["trades"]:
                    self.assertIn("profit_giveback",trade["management_analytics"])

    def test_portfolio_risk_conflict_and_expiry_use_shared_manager(self):
        from dataclasses import replace
        from tests.manager_fixtures import candidate
        def conflicting(known,prices,contracts,now,settings,**kw):
            kw.pop("configurations",None)
            rows,waits=self.source(known,prices,contracts,now,settings,**kw)
            if rows:
                other=candidate("reversal",direction="SHORT",key="opposite",account_id=kw["account"],profile=kw["profile"],
                    created_at=now.isoformat(),confirmed_at=now.isoformat(),quote_at=now.isoformat(),expires_at=(now+pd.Timedelta(minutes=2)).isoformat())
                rows.append(other)
            return rows,waits
        with patch("goxtrade.research.validation_lab.candidates_at",side_effect=conflicting):
            request={**self.request,"strategies":["crt","reversal"]}
            record=self.finish(replay.create(request)["id"])
            self.assertFalse(record["state"]["trades"])
            self.assertTrue(any(r["eligibility"]=="CONFLICTED" for r in record["state"]["decisions"]))
        with patch("goxtrade.research.validation_lab.candidates_at",side_effect=self.source):
            request={**self.request,"execution":{**self.request["execution"],"max_trade_risk":1}}
            record=self.finish(replay.create(request)["id"])
            self.assertFalse(record["state"]["positions"])
            self.assertTrue(any(r["eligibility"]=="RISK_BLOCKED" for r in record["state"]["decisions"]))

    def test_recorded_intrabar_modes_use_original_evaluator_and_persist_observation(self):
        pack=import_ticks(dict(dataset=self.dataset["id"],source="TEST FIXTURE ONLY",csv=self.ticks().to_csv(index=False),complete_recording=True))
        for mode in ("REALTIME","ANTICIPATORY"):
            created=replay.create({**self.request,"strategies":["vwap_ema_cross"],"ticks":pack["id"],"configurations":{"vwap_ema_cross":{"entry_mode":mode}}})
            seen=[]
            def evaluate(snapshot,price,now,config,**kw):
                self.assertTrue((pd.to_datetime(snapshot["time"],utc=True)<=now).all())
                seen.append((kw.get("sequence"),kw.get("previous")))
                return dict(signal="WAIT",reason="TEST FIXTURE observation"),pd.DataFrame(),dict(sequence=kw["sequence"],mode=mode)
            with patch("goxtrade.strategies.vwap_ema_cross.evaluate_vwap_ema_cross",side_effect=evaluate):
                for _ in range(7):replay.action(created["id"],dict(action="step"))
            self.assertGreaterEqual(len(seen),3)
            self.assertEqual(seen[-1][1]["sequence"],seen[-2][0])
            record=store.get(created["id"])
            self.assertEqual(record["vwap_observation"]["mode"],mode)
            self.assertLessEqual(len(record["tick_partials"]),3)
            replay.loaded.cache_clear()
            self.assertEqual(replay.detail(created["id"])["next_index"],7)

    def test_saved_actual_trade_bridge_remains_readonly_and_requires_reconciliation(self):
        from goxtrade.replay.replay_adapter import import_saved_ticks
        with closing(live_store.connect()) as conn:
            conn.executemany("INSERT INTO live_ticks(symbol,contract_id,event_type,price,volume,event_time,received_at) VALUES(?,?,'trade',?,?,?,?)",
                [("MNQ=F",r.contract_id,r.price,r.volume,r.time,r.time) for r in self.ticks().itertuples()])
            conn.commit()
            before=conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0]
        saved=import_saved_ticks(dict(dataset=self.dataset["id"],complete_recording=True))
        self.assertEqual(saved["event_count"],24)
        with closing(live_store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM live_ticks").fetchone()[0],before)

    def test_checkpoint_does_not_mutate_previous_open_exposure_or_history(self):
        from goxtrade.research.portfolio_backtest import prepare_portfolio
        data=[("MNQ",CONTRACT,self.frame)];prepared=prepare_portfolio(data)
        a=run_portfolio_backtest(data,ExecutionPolicy(commission_per_side=.5),candidate_source=self.source,max_steps=3,prepared=prepared)
        cp={**a["checkpoint"],"state":a["state"]}
        frozen=copy.deepcopy(cp)
        run_portfolio_backtest(data,ExecutionPolicy(commission_per_side=.5),candidate_source=self.source,max_steps=3,checkpoint=cp,prepared=prepared)
        self.assertEqual(cp,frozen)

    def test_single_playback_ownership_and_unsupported_schema_preserve_records(self):
        a=store.get(replay.create(self.request)["id"])
        b=store.get(replay.create(self.request)["id"])
        a["status"]="playing";store.save(a)
        b["status"]="playing"
        with self.assertRaisesRegex(ValueError,"other replay"):store.save(b)
        with closing(store.connect()) as conn:
            conn.execute("UPDATE replay_schema SET version=999");conn.commit()
        with self.assertRaisesRegex(ValueError,"Unsupported replay schema"):store.get(a["id"])


if __name__=="__main__":unittest.main()
