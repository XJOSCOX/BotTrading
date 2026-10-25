import unittest
from goxtrade.execution.executed_results import results, summary


class ExecutedTests(unittest.TestCase):
    def test_fills_from_replaced_accounts_do_not_mix(self):
        job = dict(alert_id=1, state="Closed", account_id=101, order_id=10, quantity=1, side=0, contract_id="MES", closed_confirmed_at="2026-09-17T03:02:00Z")
        entry = dict(id=1, accountId=101, orderId=10, size=1, side=0, contractId="MES", creationTimestamp="2026-09-17T03:00:00Z", profitAndLoss=None, fees=0)
        exit = dict(entry, id=2, orderId=11, side=1, creationTimestamp="2026-09-17T03:01:00Z", profitAndLoss=10)
        other_account = dict(exit, id=3, accountId=202, profitAndLoss=999)
        self.assertEqual(results([job], [entry, exit, other_account])[1]["net"], 10)

    def test_only_confirmed_bot_round_trip_counts(self):
        job = dict(alert_id=1,state="Closed",order_id=10,quantity=2,side=0,contract_id="MES",closed_confirmed_at="2026-09-17T03:02:00Z")
        entry = dict(id=1,orderId=10,size=2,side=0,contractId="MES",creationTimestamp="2026-09-17T03:00:00Z",profitAndLoss=None,fees=1,commissions=.5)
        exit = dict(entry,id=2,orderId=11,side=1,creationTimestamp="2026-09-17T03:01:00Z",profitAndLoss=10)
        matched = results([job],[entry,exit])
        self.assertEqual(matched[1]["net"],7)
        self.assertEqual(summary(matched)["wins"],1)
        self.assertEqual(results([{**job,"alert_id":-1}],[entry,exit]),{})
        self.assertEqual(results([{**job,"state":"Open"}],[entry,exit]),{})
        self.assertEqual(results([job],[entry]),{})
        self.assertEqual(results([job],[entry,{**exit,"voided":True}]),{})
        self.assertEqual(results([job],[entry,exit,{**entry,"id":3,"orderId":99}]),{})
