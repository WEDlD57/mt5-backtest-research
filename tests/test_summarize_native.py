"""Small complete-journal fixtures for the portable native result summarizer."""

import csv
import json
from pathlib import Path
import tempfile
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))

from summarize_native import analyze, summarize, TRADE_FIELDS


DEAL_FIELDS = ("time", "type", "entry", "volume", "price", "profit", "swap",
               "commission", "positionid", "fee", "dealid")
OPPORTUNITY_FIELDS = ("time", "one_lot_stop_loss_usd", "SLdistance")
ENTRY_TIME = "2026.01.13 08:00:00"
EXIT_TIME = "2026.01.13 09:00:00"


def deal(entry="in", volume="1", side="buy", price="2000", profit="0", swap="0",
         commission="0", fee="0", timestamp=ENTRY_TIME, identifier="1"):
    return dict(zip(DEAL_FIELDS, (timestamp, side, entry, volume, price, profit, swap,
                                  commission, "1", fee, identifier)))


class NativeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.deals = self.root / "deals.csv"
        self.opportunities = self.root / "opportunities.csv"
        self.write_csv(self.opportunities, OPPORTUNITY_FIELDS, [{
            "time": ENTRY_TIME, "one_lot_stop_loss_usd": "200", "SLdistance": "2",
        }])

    @staticmethod
    def write_csv(path, fields, rows):
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def winning_position(self, commission="-5", fee="0"):
        return [deal(commission=commission, fee=fee), deal(
            entry="out", side="sell", price="2001", profit="100", swap="-2",
            timestamp=EXIT_TIME, identifier="2",
        )]

    def run_summary(self, rows, initial="10000"):
        self.write_csv(self.deals, DEAL_FIELDS, rows)
        return summarize(self.deals, self.opportunities, "fixture", initial)

    def test_native_fees_are_credited_once_and_stress_doubles_total_targets(self):
        result, trades = self.run_summary(self.winning_position(commission="-4", fee="-1"))
        trade = trades[0]
        self.assertEqual(trade["native_net_usd"], 93)
        self.assertEqual(trade["native_commission_and_fee_usd"], -5)
        self.assertEqual(trade["additional_cost_usd"], 22)  # (7-5) + 20
        self.assertEqual(trade["adjusted_net_usd"], 71)  # 100 - 2 - 7 - 20
        self.assertEqual(trade["doubled_additional_cost_net_usd"], 44)  # 100 - 2 - 14 - 40
        self.assertAlmostEqual(result["doubled_additional_cost_return_pct"], 0.44)
        self.assertEqual(trade["effective_contract_from_deals"], 100)
        self.assertEqual(trade["planned_stop_risk_usd"], 200)

    def test_native_fees_above_target_are_retained(self):
        _, trades = self.run_summary(self.winning_position(commission="-9"))
        self.assertEqual(trades[0]["native_net_usd"], 89)
        self.assertEqual(trades[0]["additional_cost_usd"], 20)
        self.assertEqual(trades[0]["adjusted_net_usd"], 69)

    def test_return_uses_actual_starting_balance_100k_vs_10k(self):
        ten, _ = self.run_summary(self.winning_position(), "10000")
        hundred, _ = self.run_summary(self.winning_position(), "100000")
        self.assertEqual(ten["adjusted_net_usd"], hundred["adjusted_net_usd"])
        self.assertAlmostEqual(ten["adjusted_return_pct"], 0.71)
        self.assertAlmostEqual(hundred["adjusted_return_pct"], 0.071)
        self.assertAlmostEqual(ten["doubled_additional_cost_return_pct"],
                               10 * hundred["doubled_additional_cost_return_pct"])

    def test_incomplete_and_unbalanced_journals_are_rejected(self):
        cases = [
            ([deal()], "Incomplete"),
            ([deal(), deal(entry="out", side="sell", volume="0.9", timestamp=EXIT_TIME,
                           identifier="2")], "Incomplete"),
            ([deal(), deal(entry="out", side="sell", volume="1.1", timestamp=EXIT_TIME,
                           identifier="2")], "exceeds"),
            ([deal(entry="out", side="sell")], "exit before entry"),
        ]
        for rows, error in cases:
            with self.subTest(error=error, rows=len(rows)):
                with self.assertRaisesRegex(ValueError, error):
                    self.run_summary(rows)

    def test_reversal_and_wrong_side_exit_are_rejected(self):
        for rows, message in [
            ([deal(entry="inout")], "inout"),
            ([deal(), deal(entry="out", side="buy", timestamp=EXIT_TIME,
                           identifier="2")], "opposite side"),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.run_summary(rows)

    def test_partial_exits_charge_overlay_on_entry_volume_once(self):
        result, trades = self.run_summary([
            deal(commission="-5"),
            deal(entry="out", side="sell", volume="0.4", price="2001", profit="40",
                 timestamp="2026.01.13 08:30:00", identifier="2"),
            deal(entry="out", side="sell", volume="0.6", price="2001", profit="60", swap="-2",
                 timestamp=EXIT_TIME, identifier="3"),
        ])
        self.assertEqual(result["native_trades"], 1)
        self.assertEqual(trades[0]["lots"], 1)
        self.assertEqual(trades[0]["adjusted_net_usd"], 71)

    def test_duplicate_deal_identifier_is_rejected(self):
        rows = self.winning_position()
        rows[1]["dealid"] = rows[0]["dealid"]
        with self.assertRaisesRegex(ValueError, "duplicate deal"):
            self.run_summary(rows)

    def test_missing_exact_risk_match_is_explicit(self):
        rows = self.winning_position()
        rows[0]["time"] = "2026.01.13 08:00:01"
        result, trades = self.run_summary(rows)
        self.assertIsNone(trades[0]["planned_stop_risk_usd"])
        self.assertIsNone(trades[0]["adjusted_net_R"])
        self.assertEqual(result["trades_without_matched_planned_risk"], 1)

    def test_zero_trades_writes_valid_json_and_header_only_trade_csv(self):
        self.write_csv(self.deals, DEAL_FIELDS, [])
        self.write_csv(self.opportunities, OPPORTUNITY_FIELDS, [])
        out = self.root / "results"
        result = analyze(self.deals, self.opportunities, out, "empty", "100000")
        self.assertEqual(result["status"], "no_trades")
        self.assertEqual(result["native_trades"], 0)
        self.assertEqual(result["adjusted_return_pct"], 0)
        self.assertEqual(result["adjusted_closed_balance_max_drawdown_pct"], 0)
        self.assertIsNone(result["adjusted_win_rate_pct"])
        self.assertIsNone(result["median_contract_from_native_deals"])
        encoded = (out / "empty_native.json").read_text()
        self.assertNotIn("NaN", encoded)
        self.assertNotIn(str(self.root), encoded)
        self.assertEqual(json.loads(encoded), result)
        with (out / "empty_native_adjusted_trades.csv").open(newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, list(TRADE_FIELDS))
            self.assertEqual(list(reader), [])


if __name__ == "__main__":
    unittest.main()
