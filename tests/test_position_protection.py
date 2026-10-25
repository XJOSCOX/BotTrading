from contextlib import closing
import sqlite3
import unittest

from goxtrade.execution.position_protection import (take_profit_bracket, broker_transport, reserve_exit, reconcile_exit)
from tests.manager_fixtures import NOW


class ProtectionTests(unittest.TestCase):
    def test_bracket_adapter_disabled_and_explicitly_gated(self):
        payload = dict(stopLossBracket=dict(ticks=-20, type=4), accountId=1)
        self.assertEqual(take_profit_bracket(payload), payload)
        with self.assertRaises(ValueError):
            take_profit_bracket(payload, enabled=True, verified_ticks=20)
        result = take_profit_bracket(payload, enabled=True, verified_ticks=20, auto_oco_verified=True, signed_ticks_reviewed=True)
        self.assertEqual(result["stopLossBracket"], payload["stopLossBracket"])
        self.assertEqual(result["takeProfitBracket"], dict(ticks=20, type=1))
        with self.assertRaises(ValueError):
            broker_transport(payload)

    def test_unknown_partial_missing_protection_and_safe_reconcile(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            identifier = reserve_exit(conn, account=1, trade_id="trade", contract_id="contract", quantity=1, position_quantity=3, parent_order_id=10, direction="LONG", reason="partial")
            position = dict(accountId=1, contractId="contract", size=3, type=1)
            stop = dict(accountId=1, contractId="contract", size=3, type=4, side=1, parentOrderId=10, stopPrice=95.)
            unknown = reconcile_exit(conn, identifier, account=1, position=position, orders=[stop], snapshot_at=NOW, now=NOW, response=dict(success=False, errorCode=7))
            self.assertEqual(unknown["status"], "UNKNOWN")
            self.assertTrue(unknown["new_entries_blocked"])
            position["size"] = 2
            missing = reconcile_exit(conn, identifier, account=1, position=position, orders=[stop], snapshot_at=NOW, now=NOW)
            self.assertEqual(missing["status"], "AWAITING_PROTECTION")
            stop["size"] = 2
            result = reconcile_exit(conn, identifier, account=1, position=position, orders=[stop], snapshot_at=NOW, now=NOW)
            self.assertEqual(result["status"], "CONFIRMED")

    def test_orphaned_order_flat_is_not_safe_and_no_blind_retry(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            kwargs = dict(account=1, trade_id="trade", contract_id="contract", quantity=1, position_quantity=1, parent_order_id=10, direction="LONG", reason="exit")
            identifier = reserve_exit(conn, **kwargs)
            self.assertIsNone(reserve_exit(conn, **kwargs))
            order = dict(accountId=1, contractId="contract", id=20)
            self.assertEqual(reconcile_exit(conn, identifier, account=1, position=None, orders=[order], snapshot_at=NOW, now=NOW)["status"], "AWAITING_PROTECTION")
            self.assertEqual(reconcile_exit(conn, identifier, account=1, position=None, orders=[], snapshot_at=NOW, now=NOW)["status"], "CLOSED")

    def test_oversized_or_foreign_exits_rejected(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            with self.assertRaises(ValueError):
                reserve_exit(conn, account=1, trade_id="trade", contract_id="contract", quantity=2, position_quantity=1, parent_order_id=10, direction="LONG", reason="exit")

    def test_rejected_cancel_competing_order_stale_and_reversal_remain_blocked(self):
        with closing(sqlite3.connect(":memory:")) as conn:
            identifier = reserve_exit(conn, account=1, trade_id="trade", contract_id="contract", quantity=1, position_quantity=3, parent_order_id=10, direction="LONG", reason="partial")
            position = dict(accountId=1, contractId="contract", size=2, type=1)
            stop = dict(accountId=1, contractId="contract", size=2, type=4, side=1, parentOrderId=10, stopPrice=95.)
            args = dict(account=1, position=position, orders=[stop], snapshot_at=NOW, now=NOW)
            result = reconcile_exit(conn, identifier, **{**args, "orders":[stop, {**stop,"type":1}]}, response=dict(success=False, errorCode=2))
            self.assertEqual(result["status"], "AWAITING_PROTECTION")
            self.assertTrue(result["new_entries_blocked"])
            for changes in (dict(now="2026-10-22T15:01:00Z"), dict(account=2), dict(position={**position,"type":2}), dict(position={**position,"size":4})):
                with self.assertRaises(ValueError):
                    reconcile_exit(conn, identifier, **{**args, **changes})
            result = reconcile_exit(conn, identifier, **args)
            self.assertEqual(result["status"], "CONFIRMED")
