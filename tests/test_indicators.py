"""Unit tests for the pure-stdlib indicators (deterministic, no network)."""
import math
import unittest

from mind_shot import indicators as ind


class TestIndicators(unittest.TestCase):
    def test_rma_seed_and_step(self):
        # seed at first value, then prev + (x-prev)/n
        self.assertEqual(ind.rma([2.0, 4.0], 2), [2.0, 3.0])

    def test_rma_carries_none(self):
        out = ind.rma([None, 2.0, None, 4.0], 2)
        self.assertIsNone(out[0])
        self.assertEqual(out[1], 2.0)
        self.assertEqual(out[2], 2.0)   # None carries previous
        self.assertEqual(out[3], 3.0)

    def test_sma(self):
        self.assertEqual(ind.sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_rolling_std_population(self):
        out = ind.rolling_std([1, 2, 3], 2, ddof=0)
        self.assertIsNone(out[0])
        self.assertAlmostEqual(out[1], 0.5)
        self.assertAlmostEqual(out[2], 0.5)

    def test_zscore(self):
        out = ind.zscore([1, 2, 3], 2)
        self.assertAlmostEqual(out[1], 1.0, places=6)
        self.assertAlmostEqual(out[2], 1.0, places=6)

    def test_rsi_all_gains_is_100(self):
        out = ind.rsi([1, 2, 3, 4, 5], 2)
        self.assertEqual(out[-1], 100.0)

    def test_rsi_all_losses_is_0(self):
        out = ind.rsi([5, 4, 3, 2, 1], 2)
        self.assertEqual(out[-1], 0.0)

    def test_rsi_bounds(self):
        closes = [10, 11, 10.5, 12, 11.5, 13, 12, 14, 13, 15, 14, 16]
        for v in ind.rsi(closes, 14):
            if v is not None:
                self.assertTrue(0.0 <= v <= 100.0)

    def test_atr_nonnegative(self):
        highs = [10, 11, 12, 11, 13]
        lows = [9, 10, 10, 10, 11]
        closes = [9.5, 10.5, 11, 10.5, 12]
        for v in ind.atr(highs, lows, closes, 2):
            if v is not None:
                self.assertGreaterEqual(v, 0.0)

    def test_adx_bounds(self):
        n = 60
        highs = [100 + math.sin(i / 3) * 5 + i * 0.2 for i in range(n)]
        lows = [h - 2 for h in highs]
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        for v in ind.adx(highs, lows, closes, 14):
            if v is not None:
                self.assertTrue(0.0 <= v <= 100.0)

    def test_stochastic_k_at_high_is_100(self):
        # close equals the rolling high → %K ~ 100
        highs = [10, 11, 12, 13, 14]
        lows = [5, 6, 7, 8, 9]
        closes = [10, 11, 12, 13, 14]
        out = ind.stochastic_k(highs, lows, closes, 3)
        self.assertAlmostEqual(out[-1], 100.0, places=2)

    def test_stochastic_k_at_low_is_0(self):
        # close equal to the rolling-window low → %K ~ 0
        highs = [15, 15, 15, 15, 15]
        lows = [5, 5, 5, 5, 5]
        closes = [10, 10, 10, 10, 5]
        out = ind.stochastic_k(highs, lows, closes, 3)
        self.assertAlmostEqual(out[-1], 0.0, places=2)

    def test_rolling_vwap_equal_volume_is_mean_typical(self):
        highs = [10, 12]; lows = [8, 10]; closes = [9, 11]; vols = [1, 1]
        out = ind.rolling_vwap(highs, lows, closes, vols, 2)
        # typical = (h+l+c)/3 → 9 and 11; equal vol → mean 10
        self.assertAlmostEqual(out[-1], 10.0, places=6)

    def test_vwap_deviation_sign(self):
        # price above vwap → positive z
        highs = [10, 10, 10, 20]; lows = [10, 10, 10, 20]
        closes = [10, 10, 10, 20]; vols = [1, 1, 1, 1]
        out = ind.vwap_deviation_z(highs, lows, closes, vols, 3)
        self.assertIsNotNone(out[-1])
        self.assertGreater(out[-1], 0.0)


if __name__ == "__main__":
    unittest.main()
