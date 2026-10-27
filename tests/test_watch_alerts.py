import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from goxtrade.data import live_store
from goxtrade.execution import practice_executor as e
from goxtrade.bot.watch_alerts import clear_watch_alerts,reconcile_closed_trades
from goxtrade.bot.signal_lifecycle import advance_signal


class ClearWatchTests(unittest.TestCase):
    def broker_fixture(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        patcher=patch.object(live_store,'DB_PATH',Path(folder.name)/'closed.db');patcher.start();self.addCleanup(patcher.stop)
        self.job=dict(alert_id=1,account_id=41,state='Closed',fill_price=100.,quantity=1,side=0,order_id=7,contract_id='CON.F.US.MNQ.Z26',closed_confirmed_at='2026-10-26T14:02:00+00:00')
        self.alert=dict(status='Active',symbol='NQ=F',strategy='VWAP EMA Cross')
        with closing(live_store.connect()) as conn:
            conn.executescript('CREATE TABLE practice_jobs(alert_id INTEGER PRIMARY KEY,record TEXT); CREATE TABLE leader_jobs(alert_id INTEGER PRIMARY KEY,record TEXT); CREATE TABLE practice_fills(id INTEGER PRIMARY KEY,record TEXT); CREATE TABLE bot_alert_history(id INTEGER PRIMARY KEY,record TEXT); CREATE TABLE signal_lifecycle(symbol TEXT,strategy TEXT,state TEXT); CREATE TABLE strategy_event_consumption(setup_id TEXT PRIMARY KEY,alert_id INTEGER);')
            conn.execute('INSERT INTO practice_jobs VALUES(1,?)',(json.dumps(self.job),))
            conn.execute('INSERT INTO bot_alert_history VALUES(1,?)',(json.dumps(self.alert),))
            conn.execute('INSERT INTO signal_lifecycle VALUES(?,?,?)',('NQ=F','VWAP EMA Cross',json.dumps(dict(active=self.alert,event_id=1,seen='old',cursor=7))))
            conn.execute("INSERT INTO strategy_event_consumption VALUES('consumed-crossover',1)");conn.commit()

    def test_confirmed_broker_close_releases_lifecycle_without_guessing_fill_or_reentering(self):
        self.broker_fixture()
        self.assertEqual(reconcile_closed_trades('practice',41),1)
        with closing(live_store.connect()) as conn:
            alert=json.loads(conn.execute('SELECT record FROM bot_alert_history').fetchone()[0])
            state=json.loads(conn.execute('SELECT state FROM signal_lifecycle').fetchone()[0])
            self.assertEqual(json.loads(conn.execute('SELECT record FROM practice_jobs').fetchone()[0]),self.job)
            self.assertEqual(tuple(conn.execute('SELECT * FROM strategy_event_consumption').fetchone()),('consumed-crossover',1))
        self.assertEqual(alert['status'],'Closed');self.assertIsNone(alert['exit_price']);self.assertIsNone(alert['exit_time'])
        self.assertEqual(alert['broker_close_confirmed_at'],self.job['closed_confirmed_at'])
        self.assertIsNone(state['active']);self.assertEqual(state['seen'],'old');self.assertEqual(state['cursor'],7)
        candidate=dict(signal='LONG',entry=100.,stop=95.,target=110.)
        state,_=advance_signal(state,candidate,'old',[dict(id=8,price=100.)]);self.assertIsNone(state['active'])
        state,_=advance_signal(state,candidate,'new',[dict(id=9,price=100.)]);self.assertIsNotNone(state['active'])

    def test_other_account_ownership_and_unknown_outcomes_are_not_cleared(self):
        self.broker_fixture()
        with closing(live_store.connect()) as conn:
            conn.execute('INSERT INTO leader_jobs VALUES(1,?)',(json.dumps(dict(state='Open')),));conn.commit()
        self.assertEqual(reconcile_closed_trades('practice',41),0)
        with closing(live_store.connect()) as conn:
            conn.execute('DELETE FROM leader_jobs');conn.execute('UPDATE practice_jobs SET record=?',(json.dumps({**self.job,'state':'Unknown'}),));conn.commit()
        self.assertEqual(reconcile_closed_trades('practice',41),0)
        with closing(live_store.connect()) as conn:
            self.assertEqual(json.loads(conn.execute('SELECT record FROM bot_alert_history').fetchone()[0])['status'],'Active')

    def test_actual_exit_fill_can_arrive_later_and_updates_once(self):
        self.broker_fixture();reconcile_closed_trades('practice',41)
        with closing(live_store.connect()) as conn:
            for i,side,order,price,pnl,stamp in ((1,0,7,100.,None,'14:00'),(2,1,8,101.,2.,'14:01')):
                fill=dict(id=i,accountId=41,contractId=self.job['contract_id'],orderId=order,side=side,size=1,price=price,profitAndLoss=pnl,fees=.36,creationTimestamp=f'2026-10-26T{stamp}:00+00:00')
                conn.execute('INSERT INTO practice_fills VALUES(?,?)',(i,json.dumps(fill)))
            conn.commit()
        self.assertEqual(reconcile_closed_trades('practice',41),1)
        self.assertEqual(reconcile_closed_trades('practice',41),0)
        with closing(live_store.connect()) as conn:
            alert=json.loads(conn.execute('SELECT record FROM bot_alert_history').fetchone()[0])
        self.assertEqual(alert['exit_price'],101.);self.assertEqual(alert['exit_time'],'2026-10-26T14:01:00+00:00')

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
