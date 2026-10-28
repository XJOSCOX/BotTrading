"""Practice-only confirmation selection; no broker or production settings access."""
from contextlib import closing
from pathlib import Path
from datetime import timedelta, datetime, timezone
import tempfile
import unittest
from unittest.mock import patch

from goxtrade.bot import bot_controls
from goxtrade.data import live_store
from goxtrade.strategies import entry_confirmation as c
from tests import test_entry_confirmation as fixtures


class ConfirmationModeTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ConfirmationTests()
        fixture.setUp()
        self.signal = {**fixture.signal, "strategy_id": "crt"}
        self.bars, self.now = fixture.bars, fixture.now
        self.bars.loc[15, "close"] = 101

    def evaluate(self, mode="standard", profile="practice", price=101):
        return c.evaluate(self.signal, self.bars, price, self.now, mode=mode, profile=profile)

    def test_standard_confirms_without_one_minute_break_for_all_five(self):
        for strategy in c.LEGACY_STRATEGIES:
            self.signal["strategy_id"] = strategy
            with self.subTest(strategy=strategy):
                self.assertEqual(self.evaluate()["state"], "Confirmed")
                self.assertEqual(self.evaluate("strict")["state"], "Waiting")
                self.assertEqual(self.evaluate()["entry_confirmation_mode"], "standard")

    def test_leader_remains_strict(self):
        result = self.evaluate(profile="leader")
        self.assertEqual(result["state"], "Waiting")
        self.assertEqual(result["entry_confirmation_mode"], "strict")

    def test_other_strategies_do_not_receive_standard_confirmation(self):
        self.signal["strategy_id"] = "unknown"
        self.assertEqual(self.evaluate()["state"], "Waiting")
        self.signal.update(strategy_id="vwap_ema_cross", entry_policy="indicator-event-v1")
        with patch.object(c,"evaluate_indicator_entry",return_value={"state":"special"}) as special:
            self.assertEqual(self.evaluate(), {"state":"special"})
            special.assert_called_once()

    def test_standard_does_not_extend_expiration(self):
        self.now += timedelta(minutes=10)
        self.assertEqual(self.evaluate()["state"], "Cancelled")

    def test_incomplete_or_missing_five_minute_source_cannot_confirm(self):
        self.bars["complete"] = True
        self.bars.loc[14, "complete"] = False
        self.assertEqual(self.evaluate()["state"], "Waiting")
        self.bars = self.bars.drop(index=14)
        self.assertEqual(self.evaluate()["state"], "Waiting")

    def test_five_minute_opposition_and_existing_price_gates_remain(self):
        self.assertEqual(self.evaluate(price=95)["state"], "Cancelled")
        self.assertEqual(self.evaluate(price=110)["state"], "Cancelled")
        self.assertEqual(self.evaluate(price=105)["state"], "Waiting")
        self.bars.loc[14, "close"] = 99
        self.assertIn("5m", self.evaluate()["reason"])

    def test_standard_short_and_default_strict(self):
        self.signal.update(signal="SHORT", entry=99, target=90, setup_invalidation=105)
        for col in ("open", "high", "low", "close"):
            self.bars[col] = 200-self.bars[col]
        self.bars[["high", "low"]] = self.bars[["low", "high"]].to_numpy()
        self.assertEqual(self.evaluate(price=99)["state"], "Confirmed")
        self.assertEqual(c.evaluate(self.signal,self.bars,99,self.now,profile="practice")["state"], "Waiting")

    def test_saved_mode_survives_other_controls_saves_and_profiles_are_isolated(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"):
            self.assertEqual(bot_controls.read("practice")["entry_confirmation_mode"], "strict")
            bot_controls.save(["MNQ"],["CRT"],5,profile="practice",entry_confirmation_mode="standard")
            bot_controls.save(["MNQ"],["CRT"],7,profile="practice")
            self.assertEqual(bot_controls.read("practice")["entry_confirmation_mode"], "standard")
            self.assertEqual(bot_controls.read("leader")["entry_confirmation_mode"], "strict")
            with self.assertRaises(ValueError):
                bot_controls.save(["MNQ"],["CRT"],5,profile="leader",entry_confirmation_mode="standard")

    def test_live_check_reads_saved_mode_and_keeps_fresh_trade_requirement(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live_store,"DB_PATH",Path(folder)/"test.db"), patch.object(c,"PROFILE","practice"), patch.object(c,"chart_history",return_value=self.bars), patch.object(c,"contract_for_symbol",return_value="contract"):
            bot_controls.save(["MNQ"],["CRT"],5,profile="practice",entry_confirmation_mode="standard")
            self.assertEqual(c.check(self.signal,self.now)["state"], "Waiting")
            with closing(live_store.connect()) as conn:
                conn.execute("INSERT INTO live_ticks(symbol,contract_id,event_type,price,event_time,received_at) VALUES (?,?,?,?,?,?)",("NQ=F","contract","trade",101,self.now.isoformat(),self.now.isoformat()))
                conn.commit()
            result = c.check(self.signal,self.now)
            self.assertEqual(result["state"], "Confirmed")
            self.assertEqual(result["entry_confirmation_mode"], "standard")


class TradeModeRecordingTests(unittest.TestCase):
    setUp = fixtures.multi.MultiSymbolTests.setUp
    cycle_mocks = fixtures.multi.MultiSymbolTests.cycle_mocks

    def test_transmitted_job_keeps_final_confirmation_mode(self):
        from goxtrade.execution import practice_executor as e
        signal = dict(id=3,status="Active",symbol="NQ=F",strategy="CRT",signal="LONG",
                      entry=100,stop=95,entry_time=datetime.now(timezone.utc).isoformat())
        self.cycle_mocks([], [signal])
        self.stack.enter_context(patch.object(e,"quote_fresh",return_value=True))
        self.stack.enter_context(patch.object(e,"read_status",return_value={}))
        self.stack.enter_context(patch.object(e,"call",return_value=dict(contracts=[dict(id="CON.F.US.MNQ.Z26",symbolId="F.US.MNQ",activeContract=True)])))
        with patch.object(c,"check",return_value=dict(state="Confirmed",reason="Standard",price=101,entry_confirmation_mode="standard")), patch.object(e,"post",return_value=dict(success=True,orderId=500)) as broker:
            e.cycle("fixture")
        self.assertEqual(broker.call_count,1)
        self.assertEqual(e.snapshot()[2][0]["entry_confirmation_mode"], "standard")
