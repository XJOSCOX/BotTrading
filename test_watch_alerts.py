import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
import live_store
import practice_executor as e
from watch_alerts import clear_watch_alerts
from signal_lifecycle import advance_signal


class ClearWatchTests(unittest.TestCase):
    def test_closed_other_account_trade_allows_clear_without_changing_job(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"db"):
            with closing(live_store.connect()) as conn:
                conn.execute("CREATE TABLE bot_alert_history (id INTEGER PRIMARY KEY,record TEXT)")
                conn.execute("CREATE TABLE signal_lifecycle (symbol TEXT,strategy TEXT,state TEXT,PRIMARY KEY(symbol,strategy))")
                conn.execute("CREATE TABLE practice_jobs (alert_id INTEGER PRIMARY KEY,record TEXT)")
                record = dict(status="Active",symbol="ES=F",strategy="CRT")
                job = json.dumps(dict(state="Closed",fill_price=100,quantity=3,order_id=99))
                conn.execute("INSERT INTO bot_alert_history VALUES (1,?)",(json.dumps(record),))
                conn.execute("INSERT INTO signal_lifecycle VALUES ('ES=F','CRT',?)",(json.dumps(dict(event_id=1,active=record,seen="old")),))
                conn.execute("INSERT INTO practice_jobs VALUES (1,?)",(job,))
                conn.commit()
            self.assertEqual(clear_watch_alerts([1]),1)
            with closing(live_store.connect()) as conn:
                self.assertEqual(conn.execute("SELECT record FROM practice_jobs WHERE alert_id=1").fetchone()[0],job)
                self.assertEqual(json.loads(conn.execute("SELECT record FROM bot_alert_history WHERE id=1").fetchone()[0])["status"],"Dismissed")

    def test_clear_preserves_orders_history_and_waits_for_new_setup(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"db"):
            with closing(live_store.connect()) as conn:
                conn.execute("CREATE TABLE bot_alert_history (id INTEGER PRIMARY KEY,record TEXT)")
                conn.execute("CREATE TABLE signal_lifecycle (symbol TEXT,strategy TEXT,state TEXT,PRIMARY KEY(symbol,strategy))")
                conn.execute("CREATE TABLE leader_jobs (alert_id INTEGER PRIMARY KEY,record TEXT)")
                for number,strategy in ((1,"CRT"),(2,"ORB")):
                    record=dict(status="Active",symbol="NQ=F",strategy=strategy)
                    conn.execute("INSERT INTO bot_alert_history VALUES (?,?)",(number,json.dumps(record)))
                    conn.execute("INSERT INTO signal_lifecycle VALUES (?,?,?)",("NQ=F",strategy,json.dumps(dict(event_id=number,active=record,seen="old"))))
                conn.execute("INSERT INTO leader_jobs VALUES (2,?)",(json.dumps(dict(state="Open")),))
                conn.commit()
            self.assertEqual(clear_watch_alerts([1,2]),1)
            with closing(live_store.connect()) as conn:
                self.assertEqual(json.loads(conn.execute("SELECT record FROM bot_alert_history WHERE id=1").fetchone()[0])["status"],"Dismissed")
                self.assertEqual(json.loads(conn.execute("SELECT record FROM bot_alert_history WHERE id=2").fetchone()[0])["status"],"Active")
                state=json.loads(conn.execute("SELECT state FROM signal_lifecycle WHERE strategy='CRT'").fetchone()[0])
            candidate=dict(signal="LONG",entry=100,stop=95,target=110)
            state,_=advance_signal(state,candidate,"old",[dict(id=1,price=100)])
            self.assertIsNone(state["active"])
            state,_=advance_signal(state,candidate,"new",[dict(id=2,price=100)])
            self.assertIsNotNone(state["active"])
            with patch.object(e,"assert_other_idle"):
                self.assertFalse(e.claim(dict(alert_id=1,state="Intent")))
