"""Reject statistically empty weekly resampling in both benchmark engines."""

from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import benchmark
import benchmark_revision


class NoResamplingExpected:
    def integers(self, *args, **kwargs):
        raise AssertionError("Insufficient weekly blocks must not be resampled")


def trade(day, net_r):
    return {"entry_time": day + "T08:00:00", "exit_time": day + "T20:00:00", "net_R": net_r}


class WeeklyBootstrapCases:
    def assert_unavailable(self, result, calendar_weeks, nonempty_weeks):
        self.assertEqual(result["interval_status"], "insufficient_weekly_blocks")
        self.assertEqual(result["net_expectancy_R_95pct_interval"], [None, None])
        self.assertEqual(result["calendar_weeks"], calendar_weeks)
        self.assertEqual(result["nonempty_weekly_blocks"], nonempty_weeks)
        self.assertEqual(result["zero_trade_weeks"], calendar_weeks - nonempty_weeks)
        self.assertEqual(result["replications"], 0)
        self.assertEqual(result["valid_nonempty_replications"], 0)

    def test_one_positive_week_has_no_confidence_interval(self):
        result = self.engine.weekly_bootstrap(
            [trade("2026-10-26", 1.25)], "2026-10-26", "2026-10-30", NoResamplingExpected())
        self.assert_unavailable(result, calendar_weeks=1, nonempty_weeks=1)
        self.assertEqual(result["distinct_entry_days"], 1)

    def test_one_active_week_among_empty_weeks_has_no_interval(self):
        result = self.engine.weekly_bootstrap(
            [trade("2026-10-12", 1.0), trade("2026-10-13", 0.5)],
            "2026-10-05", "2026-10-26", NoResamplingExpected())
        self.assert_unavailable(result, calendar_weeks=3, nonempty_weeks=1)
        self.assertEqual(result["distinct_entry_days"], 2)

    def test_all_empty_weeks_have_no_interval(self):
        result = self.engine.weekly_bootstrap(
            [], "2026-10-05", "2026-10-26", NoResamplingExpected())
        self.assert_unavailable(result, calendar_weeks=3, nonempty_weeks=0)
        self.assertEqual(result["distinct_entry_days"], 0)

    def test_two_active_weeks_preserve_mixed_return_interval(self):
        # Weekly means are +0.5 R and -0.625 R. With two sampled blocks,
        # the original resampling calculation has these 2.5%/97.5% endpoints.
        trades = [trade("2026-10-05", 1.5), trade("2026-10-06", -0.5),
                  trade("2026-10-12", -1.5), trade("2026-10-13", 0.25)]
        result = self.engine.weekly_bootstrap(
            trades, "2026-10-05", "2026-10-19", np.random.default_rng(20261030))
        self.assertEqual(result["interval_status"], "available")
        self.assertEqual(result["calendar_weeks"], 2)
        self.assertEqual(result["nonempty_weekly_blocks"], 2)
        self.assertEqual(result["zero_trade_weeks"], 0)
        self.assertEqual(result["replications"], self.engine.N_SIMULATIONS)
        self.assertEqual(result["valid_nonempty_replications"], self.engine.N_SIMULATIONS)
        np.testing.assert_array_equal(result["net_expectancy_R_95pct_interval"], [-0.625, 0.5])
        self.assertIn("not adequate evidence", result["limitation"])


class BaselineWeeklyBootstrapTests(WeeklyBootstrapCases, unittest.TestCase):
    engine = benchmark


class RevisionWeeklyBootstrapTests(WeeklyBootstrapCases, unittest.TestCase):
    engine = benchmark_revision


if __name__ == "__main__":
    unittest.main()
