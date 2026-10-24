import unittest
import pandas as pd

from goxtrade.strategies.vwap_ema_config import VwapEmaConfig
from goxtrade.strategies.vwap_ema_cross import evaluate_vwap_ema_cross
from tests.vwap_fixtures import partial


class EntryModeTests(unittest.TestCase):
    def test_realtime_cross_and_reversal_are_provisional(self):
        cfg = VwapEmaConfig(entry_mode="REALTIME", stop_method="fixed")
        start = pd.Timestamp("2026-10-02T00:18:10Z")
        state = {}
        outcomes = []
        for sequence, price in enumerate((99., 103., 90.), 1):
            now = start+pd.Timedelta(seconds=sequence)
            signal, _, state = evaluate_vwap_ema_cross(partial(price, sequence, now), price, now, cfg,
                                                       state, sequence=sequence, quote_time=now)
            outcomes.append(signal)
        self.assertEqual([row["signal"] for row in outcomes], ["WAIT", "LONG", "SHORT"])
        self.assertTrue(outcomes[1]["provisional"])
        self.assertEqual(outcomes[1]["detection_sequence"], 2)

    def test_reconnect_or_repeated_sequence_does_not_create_a_cross(self):
        cfg = VwapEmaConfig(entry_mode="REALTIME", stop_method="fixed")
        now = pd.Timestamp("2026-10-02T00:18:10Z")
        _, _, state = evaluate_vwap_ema_cross(partial(99., 1, now), 99., now, cfg, sequence=1, quote_time=now)
        same = evaluate_vwap_ema_cross(partial(103., 1, now), 103., now, cfg, state, sequence=1, quote_time=now)[0]
        self.assertEqual(same["signal"], "WAIT")
        later = now+pd.Timedelta(seconds=20)
        reconnected = evaluate_vwap_ema_cross(partial(103., 2, later), 103., later, cfg, state, sequence=2, quote_time=later)[0]
        self.assertEqual(reconnected["signal"], "WAIT")

    def test_anticipation_requires_unique_converging_observations(self):
        cfg = VwapEmaConfig(entry_mode="ANTICIPATORY", stop_method="fixed", anticipation_observations=2)
        start = pd.Timestamp("2026-10-02T00:18:10Z")
        state = {}
        outcomes = []
        for sequence, price in enumerate((100., 100.25, 100.5), 1):
            now = start+pd.Timedelta(seconds=sequence)
            signal, _, state = evaluate_vwap_ema_cross(partial(price, sequence, now), price, now, cfg,
                                                       state, sequence=sequence, quote_time=now)
            outcomes.append(signal)
        self.assertEqual(outcomes[-1]["signal"], "ANTICIPATED_LONG", outcomes[-1]["reason"])
        self.assertEqual(outcomes[-1]["direction"], "LONG")
        self.assertLess(outcomes[-1]["indicator_distance"], 0)
        self.assertFalse(outcomes[-1]["account_eligibility"]["leader"])
