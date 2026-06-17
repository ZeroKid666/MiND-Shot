"""Unit tests for the strategy registry and entry/exit logic."""
import unittest

from mind_shot.models import ExitStyle, Side
from mind_shot.strategies import (
    STRATEGIES,
    STRATEGY_BY_ID,
    active_pairs,
    strategies_for,
)


class TestRegistry(unittest.TestCase):
    def test_exactly_five_strategies(self):
        self.assertEqual(len(STRATEGIES), 5)

    def test_unique_ids(self):
        ids = [s.id for s in STRATEGIES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_pairs(self):
        self.assertIn(("ETH", "4h"), active_pairs())
        self.assertIn(("BTC", "4h"), active_pairs())
        self.assertEqual(len(strategies_for("ETH", "4h")), 4)
        self.assertEqual(len(strategies_for("BTC", "4h")), 1)

    def test_bracket_strategies_have_tp(self):
        for s in STRATEGIES:
            if s.exit_style is ExitStyle.BRACKET:
                self.assertIsNotNone(s.tp_atr)
            else:
                self.assertIsNone(s.tp_atr)
                self.assertIsNotNone(s.mean_price_key)


class _StubSeries(dict):
    """Minimal series with a single index 0 for entry/exit unit testing."""


def _series(source_key, value, adx, mean_key=None, mean_val=None):
    s = {"adx": [adx], source_key: [value]}
    if mean_key:
        s[mean_key] = [mean_val]
    return s


class TestEntryExit(unittest.TestCase):
    def setUp(self):
        self.vwap = STRATEGY_BY_ID["vwap_bracket_eth"]
        self.zrev = STRATEGY_BY_ID["zscore_revert_btc"]

    def test_entry_long_when_below_threshold_and_adx_ok(self):
        s = _series("vwap_z", -2.5, adx=20)
        self.assertIs(self.vwap.entry(s, 0), Side.LONG)

    def test_entry_short_when_above_threshold(self):
        s = _series("vwap_z", 2.5, adx=20)
        self.assertIs(self.vwap.entry(s, 0), Side.SHORT)

    def test_no_entry_when_adx_too_high(self):
        s = _series("vwap_z", -2.5, adx=30)   # trending → gated out
        self.assertIsNone(self.vwap.entry(s, 0))

    def test_no_entry_inside_band(self):
        s = _series("vwap_z", -1.0, adx=20)
        self.assertIsNone(self.vwap.entry(s, 0))

    def test_no_entry_on_none(self):
        s = _series("vwap_z", None, adx=20)
        self.assertIsNone(self.vwap.entry(s, 0))

    def test_revert_exit_long_when_back_to_mean(self):
        s = _series("zscore", 0.1, adx=20)   # z>=0 → exit a long
        self.assertTrue(self.zrev.should_exit(s, 0, Side.LONG))

    def test_revert_no_exit_while_below_mean(self):
        s = _series("zscore", -1.0, adx=20)
        self.assertFalse(self.zrev.should_exit(s, 0, Side.LONG))

    def test_bracket_never_signal_exits(self):
        s = _series("vwap_z", 0.0, adx=20)
        self.assertFalse(self.vwap.should_exit(s, 0, Side.LONG))


if __name__ == "__main__":
    unittest.main()
