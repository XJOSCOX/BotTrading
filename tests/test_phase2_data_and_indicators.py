from contextlib import closing
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from goxtrade.data import live_store, feed_coverage
from goxtrade.data.chart_history import backfill_history
from goxtrade.data.strategy_history import load_strategy_minutes, initialize
from goxtrade.research.datasets import validate_dataset, validate_ticks, UnsupportedDataset
from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_indicators import indicator_frame
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross, optional_filters
from tests.vwap_fixtures import minutes, partial


class IndependentIndicatorTests(unittest.TestCase):
    def test_hand_calculated_ohlc4_volume_and_independent_decimal_ema(self):
        source = minutes([100.]*15)
        source.loc[:2, ["open", "high", "low", "close", "volume"]] = [100., 106., 98., 104., 7.]
        source.loc[3:5, ["open", "high", "low", "close", "volume"]] = [101., 103., 100., 102., 2.]
        bars = indicator_frame(source, source.iloc[-1]["time"]+pd.Timedelta(minutes=1))
        self.assertEqual(bars.iloc[0]["vwap"], 102.)
        self.assertAlmostEqual(bars.iloc[1]["vwap"], float((Decimal(102)*21+Decimal("101.5")*6)/27))
        self.assertAlmostEqual(bars.iloc[-1]["vwap"], float(Decimal(6651)/66))
        ema = Decimal(104)
        for index, close in enumerate([104., 102.]+[100.]*13):
            if index:
                ema = Decimal(".2")*Decimal(str(close))+Decimal(".8")*ema
            if index >= 8:
                self.assertAlmostEqual(bars.iloc[index]["ema"], float(ema))

    def test_explicit_unverified_minutes_cannot_confirm(self):
        source = minutes()
        source["complete"] = True
        source.loc[0, "complete"] = False
        now = source.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        signal = evaluate_vwap_ema_cross(source, 103., now, VwapEmaConfig(stop_method="fixed"), historical=True)[0]
        self.assertEqual(signal["signal"], "WAIT")

    def test_revised_history_rebaselines_intrabar_instead_of_creating_cross(self):
        config = VwapEmaConfig(entry_mode="REALTIME", stop_method="fixed")
        now = pd.Timestamp("2026-10-02T00:18:10Z")
        _, _, state = evaluate_vwap_ema_cross(partial(99., 1, now), 99., now, config, sequence=1, quote_time=now)
        changed = partial(103., 2, now+pd.Timedelta(seconds=1))
        changed.loc[0, "volume"] = 20.
        signal = evaluate_vwap_ema_cross(changed, 103., now+pd.Timedelta(seconds=1), config, state,
                                         sequence=2, quote_time=now+pd.Timedelta(seconds=1))[0]
        self.assertEqual(signal["signal"], "WAIT")
        self.assertIn("baseline", signal["reason"])

    def test_distance_limits_are_both_enforced_and_missing_atr_does_not_pass(self):
        source = minutes()
        now = source.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        bars = indicator_frame(source, now)
        bars.loc[bars.index[-1], "atr"] = 10.
        config = VwapEmaConfig(distance_enabled=True, max_distance_ticks=1., max_distance_atr=1.)
        self.assertEqual(optional_filters(bars, "LONG", 104., now, config, .25)["distance"], "failed")
        bars.loc[bars.index[-1], "atr"] = float("nan")
        config = replace(config, separation_enabled=True, separation_atr=1.)
        self.assertEqual(optional_filters(bars, "LONG", 103., now, config, .25)["separation"], "failed")

    def test_anticipation_requires_observation_momentum_not_only_prior_bar_momentum(self):
        config = VwapEmaConfig(entry_mode="ANTICIPATORY", stop_method="fixed", anticipation_observations=2)
        now = pd.Timestamp("2026-10-02T00:18:10Z")
        _, _, state = evaluate_vwap_ema_cross(partial(100., 1, now), 100., now, config, sequence=1, quote_time=now)
        # Simulate a moving VWAP making distance shrink while EMA and price fall.
        state.update(gap=-1., ema=110., price=110., convergence_count=2, anticipated_direction="LONG")
        later = now+pd.Timedelta(seconds=1)
        signal = evaluate_vwap_ema_cross(partial(100.25, 2, later), 100.25, later, config, state, sequence=2, quote_time=later)[0]
        self.assertEqual(signal["signal"], "WAIT")


class ContractHistoryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        p = patch.object(live_store, "DB_PATH", Path(folder.name)/"test.db")
        p.start()
        self.addCleanup(p.stop)
        self.contract = "CON.F.US.ENQ.Z26"
        self.now = pd.Timestamp.now(tz="UTC").floor("min")

    def trade(self, price, event, received=None, volume=1., contract=None):
        with patch.object(live_store, "utc_now", return_value=(received or event).isoformat()):
            live_store.save_trade("NQ=F", contract or self.contract, dict(price=price, volume=volume, timestamp=event.isoformat()))

    def load(self, now=None, contract=None):
        return load_strategy_minutes("NQ=F", contract or self.contract, now or self.now+pd.Timedelta(minutes=2))

    def test_cold_capture_is_not_finalized_without_declared_coverage(self):
        self.trade(100., self.now+pd.Timedelta(seconds=30))
        result = self.load()
        self.assertFalse(result.iloc[0]["complete"])
        with self.assertRaises(UnsupportedDataset):
            validate_dataset(result, self.contract)

    def test_midminute_start_and_reconnect_exclude_partial_minutes(self):
        feed_coverage.opened("NQ=F", self.contract, self.now+pd.Timedelta(seconds=20))
        self.trade(100., self.now+pd.Timedelta(seconds=25))
        self.trade(101., self.now+pd.Timedelta(minutes=1, seconds=1))
        first = self.load()
        self.assertEqual(first["complete"].tolist(), [False, True])
        feed_coverage.closed("NQ=F", self.contract, self.now+pd.Timedelta(minutes=1, seconds=10))
        feed_coverage.opened("NQ=F", self.contract, self.now+pd.Timedelta(minutes=1, seconds=30))
        self.trade(102., self.now+pd.Timedelta(minutes=1, seconds=35))
        self.assertFalse(self.load().iloc[-1]["complete"])

    def test_coverage_boundaries_are_rounded_once_without_finalizing_partial_minutes(self):
        from unittest.mock import Mock
        start=Mock()
        start.ceil.return_value=self.now+pd.Timedelta(minutes=1)
        end=self.now+pd.Timedelta(minutes=5,seconds=30)
        for minute in range(6):
            self.trade(100.,self.now+pd.Timedelta(minutes=minute,seconds=1))
        with patch.object(feed_coverage,'windows',return_value=[(start,end)]):
            result=self.load(self.now+pd.Timedelta(minutes=6))
        self.assertEqual(result['complete'].tolist(),[False,True,True,True,True,False])
        start.ceil.assert_called_once_with('min')

    def test_out_of_order_trades_preserve_event_time_ohlc_and_no_incremental_recount(self):
        self.trade(102., self.now+pd.Timedelta(seconds=30), volume=3.)
        self.trade(100., self.now+pd.Timedelta(seconds=10), received=self.now+pd.Timedelta(seconds=31), volume=2.)
        first, second = self.load(), self.load()
        self.assertEqual(first.iloc[0]["open"], 100.)
        self.assertEqual(first.iloc[0]["close"], 102.)
        self.assertEqual(first.iloc[0]["volume"], 5.)
        self.assertEqual(second.iloc[0]["volume"], 5.)

    def test_rollover_and_quote_volume_do_not_mix_contracts(self):
        self.trade(100., self.now, volume=2.)
        self.trade(200., self.now, volume=3., contract="CON.F.US.ENQ.H27")
        live_store.save_quote("NQ=F", self.contract, dict(lastPrice=100., volume=999999., timestamp=self.now.isoformat()))
        self.assertEqual(self.load().iloc[0]["volume"], 2.)
        self.assertEqual(self.load(contract="CON.F.US.ENQ.H27").iloc[0]["close"], 200.)

    def test_authoritative_backfill_replaces_partial_and_bad_refetch_cannot_overwrite(self):
        self.trade(100., self.now-pd.Timedelta(minutes=1)+pd.Timedelta(seconds=30), volume=2.)
        bar = dict(t=(self.now-pd.Timedelta(minutes=1)).isoformat(), o=99., h=102., l=98., c=101., v=20.)
        with patch("goxtrade.data.chart_history.contract_for_symbol", return_value=self.contract), \
                patch("goxtrade.data.chart_history.post", return_value=dict(success=True, bars=[bar])):
            self.assertEqual(backfill_history("NQ=F"), 1)
        loaded = self.load()
        self.assertEqual(loaded.iloc[0]["volume"], 20.)
        self.assertTrue(loaded.iloc[0]["complete"])
        for bad in ({**bar, "v": None}, {**bar, "h": 1.}, {**bar, "contractId": "OTHER"},
                    {**bar, "t": (self.now-pd.Timedelta(seconds=30)).isoformat()}):
            with self.subTest(bad=bad), patch("goxtrade.data.chart_history.contract_for_symbol", return_value=self.contract), \
                    patch("goxtrade.data.chart_history.post", return_value=dict(success=True, bars=[bad])):
                with self.assertRaises(ValueError):
                    backfill_history("NQ=F")
            self.assertEqual(self.load().iloc[0]["volume"], 20.)

    def test_invalid_and_zero_volume_have_distinct_integrity_outcomes(self):
        self.trade(100., self.now, volume=0.)
        self.assertEqual(self.load().iloc[0]["volume"], 0.)
        self.trade(100., self.now, volume=-1.)
        self.assertTrue(pd.isna(self.load().iloc[0]["volume"]))

    def test_contract_provenance_and_null_contract_rows_are_rejected(self):
        source = minutes()
        with self.assertRaises(UnsupportedDataset):
            validate_dataset(source, "OTHER")
        source["contract_id"] = "TEST.CONTRACT"
        source.loc[1, "contract_id"] = None
        with self.assertRaises(UnsupportedDataset):
            validate_dataset(source, "TEST.CONTRACT")

    def test_repeated_known_trade_ids_are_rejected_not_summed(self):
        ticks = pd.DataFrame([dict(time="2026-10-01T22:00:00Z", sequence=i, price=100., volume=1., event_id="same") for i in (1, 2)])
        with self.assertRaises(UnsupportedDataset):
            validate_ticks(ticks, "TEST.CONTRACT")

    def test_quote_updates_cannot_masquerade_as_intrabar_trade_volume(self):
        ticks = pd.DataFrame([dict(time="2026-10-01T22:00:00Z", sequence=1, price=100., volume=10000., event_type="quote")])
        with self.assertRaises(UnsupportedDataset):
            validate_ticks(ticks, "TEST.CONTRACT")

    def test_history_retrieval_timestamp_is_not_backdated_to_bar_close(self):
        bar = dict(t=(self.now-pd.Timedelta(minutes=10)).isoformat(), o=100., h=101., l=99., c=100., v=5.)
        with patch("goxtrade.data.chart_history.contract_for_symbol", return_value=self.contract), \
                patch("goxtrade.data.chart_history.post", return_value=dict(success=True, bars=[bar])):
            backfill_history("NQ=F")
        loaded = self.load()
        self.assertGreaterEqual(pd.Timestamp(loaded.iloc[0]["asof_time"]), self.now)

    def test_invalid_configuration_does_not_stop_existing_signal_exit_management(self):
        from goxtrade.bot.signal_lifecycle import track_signal, alert_history
        from goxtrade.strategies.vwap_ema_runtime import evaluate_status
        source = minutes()
        source.attrs["contract_id"] = self.contract
        now = source.iloc[-1]["time"]+pd.Timedelta(minutes=1)
        candidate = evaluate_vwap_ema_cross(source, 103., now, VwapEmaConfig(stop_method="fixed"), historical=True)[0]
        live_store.save_trade("NQ=F", self.contract, dict(price=103., volume=1., timestamp=now.isoformat()))
        track_signal("NQ=F", "VWAP EMA Cross", candidate, candidate["unique_setup_id"], True)
        live_store.save_trade("NQ=F", self.contract, dict(price=90., volume=1., timestamp=(now+pd.Timedelta(seconds=1)).isoformat()))
        with patch("goxtrade.strategies.vwap_ema_runtime.read_vwap_ema_config", side_effect=ValueError("invalid config")), \
                patch("goxtrade.strategies.vwap_ema_runtime.load_strategy_minutes", return_value=source), \
                patch("goxtrade.research.forward_paper.forward_once", return_value=None):
            status = evaluate_status("NQ=F", "VWAP EMA Cross", dict(time=now+pd.Timedelta(seconds=2), is_open=True))
        self.assertEqual(alert_history()[0]["status"], "Closed")
        self.assertIn("Invalid strategy settings", status["indicator_snapshot"]["reason"])

    def test_failed_observation_cas_cannot_repromote_anticipated_direction(self):
        from goxtrade.strategies import vwap_ema_runtime as runtime
        now = pd.Timestamp.now(tz="UTC")
        candidate = dict(signal="ANTICIPATED_LONG", raw_signal="ANTICIPATED_LONG", direction="LONG", entry=100.,
                         stop=99., target=102., unique_setup_id="a"*64, crossover_key="b"*64)
        with patch.object(runtime, "read_vwap_ema_config", return_value=VwapEmaConfig()), \
                patch.object(runtime, "load_strategy_minutes", return_value=pd.DataFrame(columns=["time"])), \
                patch.object(runtime, "latest_trade", return_value=dict(price=100., id=1, event_time=now.isoformat(), received_at=now.isoformat())), \
                patch.object(runtime.strategy_events, "observation", return_value={}), \
                patch.object(runtime.strategy_events, "latest_event", return_value=None), \
                patch.object(runtime.strategy_events, "persist", return_value=None), \
                patch.object(runtime, "evaluate_vwap_ema_cross", return_value=(candidate, pd.DataFrame(), {})), \
                patch.object(runtime, "track_signal", side_effect=lambda symbol, strategy, signal, *args: signal) as track, \
                patch("goxtrade.research.forward_paper.forward_once", return_value=None):
            status = runtime.evaluate_status("NQ=F", "VWAP EMA Cross", dict(time=now, is_open=True))
        self.assertFalse(track.call_args.args[4])
        self.assertEqual(status["signal"]["signal"], "WAIT")
        self.assertIsNone(status["indicator_snapshot"]["unique_setup_id"])

    def test_delayed_preentry_tick_cannot_close_a_new_strategy_signal(self):
        from goxtrade.bot.signal_lifecycle import advance_signal
        now = pd.Timestamp.now(tz="UTC")-pd.Timedelta(seconds=20)
        candidate = dict(strategy_id="vwap_ema_cross", signal="LONG", entry=100., stop=95., target=110., detected_at=now.isoformat())
        state, _ = advance_signal({}, candidate, "setup", [dict(id=1, price=100.)])
        state, result = advance_signal(state, candidate, "setup", [dict(id=2, price=90., event_time=(now-pd.Timedelta(seconds=1)).isoformat())])
        self.assertEqual(result["signal"], "LONG")
        state, result = advance_signal(state, candidate, "setup", [dict(id=3, price=90., event_time=(now+pd.Timedelta(seconds=1)).isoformat())])
        self.assertIsNone(state["active"])
        self.assertIn("Stop reached", result["reason"])

    def test_unverified_minutes_are_not_used_for_existing_signal_structure_exits(self):
        from goxtrade.strategies import vwap_ema_runtime as runtime
        now = pd.Timestamp.now(tz="UTC").floor("min")
        source = pd.DataFrame([dict(time=now-pd.Timedelta(minutes=i), open=100., high=101., low=99., close=100., volume=1., complete=i == 1) for i in (2, 1)])
        with patch.object(runtime, "read_vwap_ema_config", return_value=VwapEmaConfig()), \
                patch.object(runtime, "load_strategy_minutes", return_value=source), \
                patch.object(runtime, "latest_trade", return_value=None), \
                patch.object(runtime, "track_signal", side_effect=lambda symbol, strategy, candidate, *args: candidate) as track, \
                patch("goxtrade.research.forward_paper.forward_once", return_value=None):
            runtime.evaluate_status("NQ=F", "VWAP EMA Cross", dict(time=now, is_open=True))
        self.assertEqual(len(track.call_args.args[5]), 1)
        self.assertEqual(track.call_args.args[5][0]["time"], (now-pd.Timedelta(minutes=1)).isoformat())
