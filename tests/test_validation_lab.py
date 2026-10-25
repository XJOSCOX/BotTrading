from contextlib import closing
from dataclasses import replace
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import requests

from goxtrade.data import live_store,lab_store as store
from goxtrade.data.historical_quality import quality,expected_minutes,interval
from goxtrade.data.history_download import ReadOnlyHistory,HistoryUnavailable,request_metadata,download
from goxtrade.research import lab_service,validation_lab as lab
from goxtrade.research.market_regimes import classify


CONTRACT="CON.F.US.MNQ.Z26"
START="2026-10-22T14:00:00+00:00"
END="2026-10-22T15:00:00+00:00"


def metadata(**values):
    return dict(symbol="MNQ",contract_id=CONTRACT,start=START,end=END,expiration="2026-12-18",calendar_reviewed=True,
                calendar_note="Deterministic test calendar review",source="TEST FIXTURE ONLY",volume_provenance="TEST FIXTURE volume",granularity=1,**values)


def minutes(start=START,end=END):
    times=expected_minutes(start,end)
    return pd.DataFrame([dict(time=t.isoformat(),open=100.,high=101.,low=99.,close=100.,volume=10.) for t in times],columns=["time","open","high","low","close","volume"])


class LabTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path=Path(directory.name)/"lab.db"
        for mock in (patch.object(live_store,"DB_PATH",self.path),
                     patch("goxtrade.execution.projectx_client.post",side_effect=AssertionError("No real broker calls")),
                     patch("goxtrade.execution.projectx_client.login",side_effect=AssertionError("No login"))):
            mock.start();self.addCleanup(mock.stop)

    def test_quality_complete_missing_invalid_and_zero_volume(self):
        frame=minutes()
        self.assertEqual(quality(frame,metadata())["status"],"complete")
        self.assertEqual(quality(frame.iloc[:-1],metadata())["missing_candles"],1)
        for key,value in (("open",-1),("high",90),("volume",-1),("volume",float("nan")),("time","2026-10-22 14:00:00")):
            changed=frame.copy();changed.loc[0,key]=value
            self.assertEqual(quality(changed,metadata())["status"],"invalid",(key,value))
        frame.loc[0,"volume"]=0
        report=quality(frame,metadata())
        self.assertEqual(report["zero_volume_candles"],1)
        self.assertEqual(report["candles"],60)

    def test_duplicates_order_calendar_and_contract_fail_closed(self):
        frame=minutes()
        self.assertEqual(quality(pd.concat([frame,frame.iloc[:1]]),metadata())["duplicate_candles"],1)
        self.assertEqual(quality(frame.iloc[::-1],metadata())["status"],"invalid")
        unreviewed=quality(frame,{**metadata(),"calendar_reviewed":False})
        self.assertIsNone(unreviewed["coverage_percent"])
        self.assertFalse(unreviewed["eligible"])
        frame["contract_id"]="CON.F.US.MES.Z26"
        self.assertEqual(quality(frame,metadata())["invalid_candles"],60)
        self.assertEqual(quality(minutes(),{**metadata(),"granularity":5})["status"],"unsupported")

    def test_calendar_holiday_early_close_dst_and_weekend(self):
        self.assertEqual(len(expected_minutes("2026-10-24T14:00:00Z","2026-10-24T15:00:00Z")),0)
        # Thanksgiving uses the installed exchange calendar's early close, not a weekday heuristic.
        rows=expected_minutes("2026-11-26T18:00:00Z","2026-11-26T23:00:00Z")
        self.assertLess(len(rows),300)
        before=expected_minutes("2026-03-06T23:00:00Z","2026-03-07T00:00:00Z")
        after=expected_minutes("2026-03-08T22:00:00Z","2026-03-08T23:00:00Z")
        self.assertEqual(len(before),0)
        self.assertEqual(len(after),60)
        with self.assertRaises(ValueError):interval("2026-10-22",END)

    def test_atomic_dedup_provenance_and_research_isolation(self):
        first=store.save_dataset(minutes(),metadata())
        second=store.save_dataset(minutes(),metadata())
        self.assertEqual(first["id"],second["id"])
        self.assertEqual(len(store.frame(first["id"])),60)
        self.assertTrue(first["content_hash"])
        with closing(live_store.connect()) as conn:
            tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertFalse(tables & {"practice_control","leader_control","leader_loss_gate"})
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0],"ok")
        invalid=minutes();invalid.loc[0,"volume"]=-1
        with self.assertRaises(ValueError):store.save_dataset(invalid,metadata())
        self.assertEqual(len(store.read_rows("lab_datasets")),1)

    def test_download_chunking_resume_duplicates_and_actual_empty(self):
        request=request_metadata(dict(symbol="MNQ",contract_id=CONTRACT,start="2026-10-19T14:00:00Z",end="2026-10-21T14:00:00Z",expiration="2026-12-18"))
        job=store.job("history",request)
        class Provider:
            def __init__(self):self.calls=[];self.fail=True
            def bars(self,payload):
                self.calls.append(payload)
                if len(self.calls)==2 and self.fail:raise HistoryUnavailable("fixture interruption")
                row=dict(t=payload["startTime"],o=100.,h=101.,l=99.,c=100.,v=10.)
                return [row,row]
        provider=Provider()
        with self.assertRaises(HistoryUnavailable):download(job["id"],provider)
        self.assertEqual(store.get("lab_jobs",job["id"])["cursor"],"2026-10-20T14:00:00+00:00")
        provider.fail=False
        download(job["id"],provider)
        done=store.get("lab_jobs",job["id"])
        self.assertEqual(done["status"],"complete")
        self.assertEqual(len(store.frame(done["result_id"])),2)
        self.assertEqual(done["events"][0]["duplicates"],1)
        self.assertTrue(all(p["limit"]==20000 and p["includePartialBar"] is False for p in provider.calls))
        other=store.job("history",{**request,"expiration":"2026-12-19"})
        download(other["id"],type("Empty",(),{"bars":lambda self,payload:[]})())
        self.assertEqual(store.get("lab_jobs",other["id"])["quality"]["status"],"unavailable")

    def test_rate_limit_timeout_retry_bound_and_safe_auth_errors(self):
        response=requests.Response();response.status_code=429;response.headers["Retry-After"]="2"
        error=requests.HTTPError(response=response)
        sleeps=[]
        with patch("goxtrade.execution.projectx_client.login",return_value="fixture-token"),patch("goxtrade.execution.projectx_client.post",side_effect=[error,requests.Timeout(),dict(success=True,bars=[])]) as post:
            self.assertEqual(ReadOnlyHistory(sleep=sleeps.append).bars({}),[])
            self.assertEqual(post.call_count,3)
            self.assertTrue(all(call.args[0]=="/api/History/retrieveBars" for call in post.call_args_list))
        with patch("goxtrade.execution.projectx_client.login",return_value="fixture-token"),patch("goxtrade.execution.projectx_client.post",side_effect=requests.Timeout()) as post:
            with self.assertRaises(HistoryUnavailable):ReadOnlyHistory(sleep=lambda _:None).bars({})
            self.assertEqual(post.call_count,4)

    def test_conflicting_chunk_and_cursor_commit_are_atomic(self):
        job=store.job("history",metadata())
        first=minutes().iloc[:1].to_dict("records")
        store.stage_chunk(job["id"],first,END,{"bars":1})
        with self.assertRaises(ValueError):store.stage_chunk(job["id"],[{**first[0],"close":100.5}],END,{})
        self.assertEqual(store.staged_frame(job["id"]).iloc[0]["close"],100.)

    def test_claim_cancel_and_restart_are_explicit(self):
        one=store.job("history",metadata())
        two=store.job("history",{**metadata(),"expiration":"other"})
        store.claim(one["id"])
        with self.assertRaises(ValueError):store.claim(one["id"])
        with self.assertRaises(ValueError):store.claim(two["id"])
        from goxtrade.research.lab_jobs import cancel
        cancel(one["id"])
        self.assertTrue(store.get("lab_jobs",one["id"])["cancel"])
        self.assertFalse(store.stage_chunk(one["id"],[],END,{}))

    def test_all_seven_registered_strategies_and_export_without_accounts(self):
        saved=store.save_dataset(minutes(),metadata())
        request=lab.validate_request(dict(datasets=[saved["id"]],strategies=[s.id for s in lab.SPECS],start=START,end=END,execution=dict(commission_per_side=.5)))
        job=store.job("validation",request)
        lab.execute(job["id"])
        run=store.get("lab_runs",job["id"])
        self.assertEqual(run["result"]["summary"]["metrics"]["trades"],0)
        self.assertEqual(run["broker_checks"],"NOT_PERFORMED")
        self.assertEqual(len(run["request"]["strategies"]),7)
        self.assertTrue(run["code"]["commit"])
        from goxtrade.research.lab_reports import html_report,trades_csv,export_dataset
        self.assertIn("not actual account profits",html_report(run))
        self.assertIn("contract_id",trades_csv(run))
        self.assertIn(CONTRACT,"".join(export_dataset(saved["id"])))

    def test_realtime_modes_partial_coverage_and_mismatched_contracts_blocked(self):
        saved=store.save_dataset(minutes(),metadata())
        values=dict(datasets=[saved["id"]],strategies=["vwap_ema_cross"],start=START,end=END,execution=dict(commission_per_side=.5),configurations=dict(vwap_ema_cross=dict(entry_mode="REALTIME")))
        with self.assertRaisesRegex(ValueError,"ordered"):lab.validate_request(values)
        values["configurations"]={}
        partial=store.save_dataset(minutes().iloc[:-1],metadata())
        values["datasets"]=[partial["id"]]
        with self.assertRaisesRegex(ValueError,"complete reviewed"):lab.load_datasets(lab.validate_request(values))

    def test_regimes_are_causal_and_never_infer_future_labels(self):
        frame=minutes()
        when=pd.Timestamp(END)
        before=classify(frame,when)
        future=minutes("2026-10-22T15:00:00Z","2026-10-22T16:00:00Z")
        future[["open","high","low","close"]]=1000.
        self.assertEqual(classify(pd.concat([frame,future]),when),before)

    def test_actual_engine_comparisons_costs_and_trade_window(self):
        from tests.test_portfolio_backtest import signals,minutes as engine_minutes
        source=engine_minutes()
        source.loc[3,["high","close"]]=[125.,110.]
        meta={**metadata(),"start":source.iloc[0].time.isoformat(),"end":(source.iloc[-1].time+pd.Timedelta(minutes=1)).isoformat()}
        saved=store.save_dataset(source,meta)
        values=dict(datasets=[saved["id"]],strategies=["crt"],start=meta["start"],end=meta["end"],execution=dict(commission_per_side=.5),
                    exit_policy=dict(enabled=True,mode="fixed",target_method="rr",target_r=1),compare_exits=True,compare_portfolios=True,sensitivity=True)
        request=lab.validate_request(values)
        job=store.job("validation",request)
        def adapted(histories,prices,contracts,now,settings,**kw):
            kw.pop("configurations",None)
            return signals(histories,prices,contracts,now,settings,**kw)
        with patch.object(lab,"candidates_at",side_effect=adapted):lab.execute(job["id"])
        run=store.get("lab_runs",job["id"])
        self.assertEqual(run["result"]["summary"]["metrics"]["trades"],1)
        self.assertEqual(len(run["comparisons"]["exits"]["policies"]),10)
        self.assertIn("positions:2",run["comparisons"]["portfolios"])
        self.assertIn("fees +25%",run["comparisons"]["costs"])
        self.assertGreater(run["result"]["state"]["trades"][0]["costs"],0)
        self.assertTrue(lab.trade_window(run,0)["bars"])
        self.assertEqual(store.job("validation",request)["id"],job["id"])

    def test_chronological_windows_keep_frozen_parameters_and_cancel(self):
        frame=minutes(START,"2026-10-22T20:00:00Z")
        meta={**metadata(),"end":"2026-10-22T20:00:00Z"}
        saved=store.save_dataset(frame,meta)
        request=lab.validate_request(dict(datasets=[saved["id"]],strategies=["crt"],start=START,end=meta["end"],execution=dict(commission_per_side=.5),walk_forward=True))
        job=store.job("validation",request)
        with patch.object(lab,"candidates_at",return_value=([],[])):lab.execute(job["id"])
        windows=store.get("lab_runs",job["id"])["comparisons"]["chronological"]
        self.assertEqual(len(windows),5)
        self.assertTrue(all(not w["parameters_fitted"] for w in windows))
        self.assertEqual(len({w["config_hash"] for w in windows}),1)
        another=store.job("validation",{**request,"initial_balance":1000})
        store.update_job(another["id"],cancel=True)
        with self.assertRaises(InterruptedError):lab.execute(another["id"])

    def test_explicit_owner_fence_prevents_stale_chunk_commit(self):
        job=store.job("history",metadata())
        owner=store.claim(job["id"])["owner"]
        with self.assertRaises(ValueError):store.stage_chunk(job["id"],[],END,{},owner="foreign")
        with self.assertRaises(ValueError):store.update_job(job["id"],expected_owner="foreign",status="complete")
        self.assertEqual(store.get("lab_jobs",job["id"])["owner"],owner)

    def test_integrity_detects_valid_price_tampering_and_isolation(self):
        saved=store.save_dataset(minutes(),metadata())
        self.assertTrue(store.verify_dataset(saved["id"]))
        self.assertNotEqual(store.database_path(),live_store.DB_PATH)
        with closing(store.connect()) as conn:
            conn.execute("UPDATE lab_bars SET close=100.25 WHERE dataset=? AND time=?",(saved["id"],START))
            conn.commit()
        with self.assertRaisesRegex(ValueError,"integrity mismatch"):store.verify_dataset(saved["id"])
        with closing(store.connect()) as conn:
            conn.execute("UPDATE lab_schema SET version=2")
            conn.commit()
        with self.assertRaisesRegex(ValueError,"schema version"):store.get("lab_datasets",saved["id"])
        with closing(store.connect()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM lab_bars").fetchone()[0],60)
        with patch("goxtrade.data.lab_store.sqlite3.connect",side_effect=sqlite3.OperationalError("fixture unavailable")):
            self.assertIsNone(store.progress_revision())
