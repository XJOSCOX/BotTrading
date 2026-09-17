import unittest
from unittest.mock import patch
import bot_view
from executed_results import results


class ClosedAlertViewTests(unittest.TestCase):
    def test_open_points_use_fill_not_signal(self):
        row = dict(id=89,status="Active",signal="SHORT",symbol="YM=F",strategy="Reversal",entry=52271)
        job = dict(state="Open",symbol="MYM",quantity=3,fill_price=52265,side=1)
        with patch.object(bot_view.st,"html") as html, patch.object(bot_view,"feed_status",return_value="Live"):
            bot_view.history_card(row,tick=dict(price=52251),job=job)
            self.assertIn("Move from broker fill: +14.00 pts",html.call_args.args[0])
            self.assertNotIn("+20.00 pts",html.call_args.args[0])
            bot_view.history_card(dict(row,signal="LONG"),tick=dict(price=52251),job=dict(job,side=0))
            self.assertIn("-14.00 pts",html.call_args.args[0])
            bot_view.history_card(row,tick=dict(price=52251),job=dict(job,fill_price=None))
            self.assertIn("Awaiting confirmed broker fill",html.call_args.args[0])
            bot_view.history_card(row,tick=dict(price=52251))
            self.assertIn("Signal movement: +20.00 pts",html.call_args.args[0])

    def test_entry_reason_visible_and_escaped(self):
        row = dict(id=1,status="Active",signal="LONG",symbol="NQ=F",strategy="CRT",entry=100)
        with patch.object(bot_view.st,"html") as html:
            bot_view.history_card(row, decisions=[dict(time="2026-09-17T15:00:00Z",detail="Conflicting <strategy>")])
            self.assertIn("Why no entry",html.call_args.args[0])
            self.assertIn("Conflicting &lt;strategy&gt;",html.call_args.args[0])
            bot_view.history_card(row)
            self.assertIn("No entry decision recorded",html.call_args.args[0])
            bot_view.history_card(row,job=dict(state="Open",symbol="MNQ",quantity=3))
            self.assertNotIn("Why no entry",html.call_args.args[0])

    def test_monitor_badge_matches_account_and_exact_setup(self):
        signal = dict(signal="LONG", setup_time="2026-09-17T15:00:00Z")
        history = [dict(signal, id=84, symbol="NQ=F", strategy="CRT")]
        label = lambda s, jobs: bot_view.monitor_signal_label("NQ=F", "CRT", s, history, jobs)
        self.assertEqual(label(signal, {84: dict(state="Closed")}), "WAIT")
        self.assertEqual(label(signal, {84: dict(state="Open")}), "IN TRADE / LONG")
        self.assertEqual(label(signal, {}), "WATCH / LONG")
        self.assertEqual(label(dict(signal, setup_time="2026-09-17T15:15:00Z"), {84: dict(state="Closed")}), "WATCH / LONG")

    def test_closed_trade_not_active_signal(self):
        row = dict(id=84, status="Active", signal="LONG", symbol="NQ=F", strategy="CRT", entry=100)
        job = dict(state="Closed", symbol="MNQ", quantity=3, fill_price=101)
        self.assertEqual(bot_view.prioritized_alerts([row], {84: job}), ([], [row]))
        self.assertEqual(bot_view.prioritized_alerts([row], {}), ([row], []))
        with patch.object(bot_view.st, "html") as html:
            bot_view.history_card(row, job=job, result=dict(net=57.84, exit_price=110.5, closed_at="2026-09-17T15:17:51Z"))
            markup = html.call_args.args[0]
            self.assertIn("Broker exit", markup)
            self.assertIn("110.50", markup)
            self.assertNotIn("Signal Active", markup)

    def test_weighted_broker_exit(self):
        job = dict(alert_id=1,state="Closed",order_id=10,quantity=3,side=0,contract_id="MNQ",closed_confirmed_at="2026-09-17T15:18:00Z")
        entry = dict(id=1,orderId=10,size=3,side=0,contractId="MNQ",creationTimestamp="2026-09-17T15:15:00Z",price=100,profitAndLoss=None)
        exit1 = dict(entry,id=2,orderId=11,size=1,side=1,price=110,profitAndLoss=20,creationTimestamp="2026-09-17T15:17:00Z")
        exit2 = dict(exit1,id=3,size=2,price=113,profitAndLoss=52)
        self.assertEqual(results([job],[entry,exit1,exit2])[1]["exit_price"],112)
