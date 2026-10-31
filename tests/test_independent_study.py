import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
"""Synthetic checks only: no independent historical study returns are evaluated."""
from pathlib import Path
import json
import tempfile
import unittest

import numpy as np
import pandas as pd

import independent_study as study


SPECS = {"point":"0.01", "digits":"2", "tick_size":"0.01", "contract_size":"100",
         "volume_min":"0.01", "volume_max":"100", "volume_step":"0.01",
         "currency_profit":"USD", "account_currency":"USD", "stops_level_points":"0",
         "swap_mode":"4", "swap_long":"-55.74", "swap_short":"-42.819",
         "swap_rollover3days":"3", "swap_sunday":"0", "swap_monday":"1",
         "swap_tuesday":"1", "swap_wednesday":"3", "swap_thursday":"1",
         "swap_friday":"1", "swap_saturday":"0"}


def fixture(day="2026-10-26", overnight=False):
    date = pd.Timestamp(day)
    minutes = pd.DatetimeIndex([date + pd.Timedelta(hours=19), date + pd.Timedelta(hours=19,minutes=59), date + (pd.Timedelta(days=1,minutes=2) if overnight else pd.Timedelta(hours=20))])
    first = minutes + pd.to_timedelta([17, 31, 23], unit="s")
    last = minutes + pd.to_timedelta([45, 44, 48], unit="s")
    return pd.DataFrame({"time":minutes, "open":[100.0]*3,"high":[100.2]*3,
                         "low":[99.8]*3,"close":[100.0]*3,
                         "ask_open":[100.1]*3,"ask_high":[100.3]*3,
                         "ask_low":[99.9]*3,"ask_close":[100.1]*3,
                         "tick_volume":[5,8,6],"first_tick_time":first,"last_tick_time":last})


def outcome(frame, direction=1):
    validated = study.validate_minutes(frame)
    market = study.ObservedQuoteMarket(validated,SPECS)
    signal = pd.Series({"time":validated.iloc[0]["first_tick_time"], "entrybid":100.0,"ask":100.1,"ATR":1.0})
    end=int((validated.iloc[-1]["time"]+pd.Timedelta(hours=1)).timestamp())
    return market.outcome(signal,direction,end),market,signal,end


class QuoteIntegrityTests(unittest.TestCase):
    def test_full_actual_ask_is_required(self):
        for name in ("ask_open","ask_high","ask_low","ask_close"):
            with self.subTest(column=name),self.assertRaisesRegex(ValueError,"Missing required actual quote columns"):
                study.validate_minutes(fixture().drop(columns=name))

    def test_crossed_quotes_and_inconsistent_high_are_rejected(self):
        frame=fixture();frame.loc[0,"ask_open"]=99.0
        with self.assertRaisesRegex(ValueError,"OHLC"):
            study.validate_minutes(frame)
        frame=fixture();frame.loc[0,"high"]=99.0
        with self.assertRaisesRegex(ValueError,"Inconsistent"):
            study.validate_minutes(frame)

    def test_first_last_times_must_remain_in_same_minute(self):
        frame=fixture();frame.loc[0,"first_tick_time"]=frame.loc[0,"time"]-pd.Timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError,"outside"):
            study.validate_minutes(frame)
        frame=fixture();frame.loc[0,"last_tick_time"]=frame.loc[0,"time"]+pd.Timedelta(minutes=1)
        with self.assertRaisesRegex(ValueError,"outside"):
            study.validate_minutes(frame)

    def test_first_tick_cannot_follow_last_tick(self):
        frame=fixture();frame.loc[0,"first_tick_time"]=frame.loc[0,"time"]+pd.Timedelta(seconds=50)
        with self.assertRaisesRegex(ValueError,"first tick occurs after"):
            study.validate_minutes(frame)

    def test_precise_companions_are_validated_without_inventing_ticks(self):
        frame=fixture()
        frame["first_tick_time_utc"]=frame["first_tick_time"]+pd.Timedelta(milliseconds=123)
        frame["last_tick_time_utc"]=frame["last_tick_time"]+pd.Timedelta(milliseconds=987)
        result=study.validate_minutes(frame)
        self.assertEqual(result.loc[0,"first_tick_time"].second,17)
        self.assertEqual(result.loc[0,"first_tick_time_actual"].microsecond,123000)
        frame.loc[0,"first_tick_time_utc"]=frame.loc[0,"first_tick_time"]+pd.Timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            study.validate_minutes(frame)

    def test_duplicate_or_unordered_minutes_and_invalid_counts_are_rejected(self):
        frame=fixture();frame.loc[1,"time"]=frame.loc[0,"time"]
        with self.assertRaisesRegex(ValueError,"chronological"):
            study.validate_minutes(frame)
        for bad in (0,-1,1.5,np.nan):
            frame=fixture();frame["tick_volume"]=frame["tick_volume"].astype(float);frame.loc[0,"tick_volume"]=bad
            with self.subTest(count=bad),self.assertRaisesRegex(ValueError,"positive integer"):
                study.validate_minutes(frame)

    def test_coverage_rejects_an_entire_missing_evaluation_month(self):
        frame=study.validate_minutes(fixture("2023-01-02"))
        plan={"warmup_start_inclusive":"2022-10-01", "evaluation_start_inclusive":"2023-01-01", "evaluation_end_exclusive":"2023-03-01"}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,"evaluation months: 2023-02"):
                study.coverage_report(frame,plan,Path(tmp))

    def test_non_utc_clock_is_not_silently_converted(self):
        frame=fixture();frame["time"]=frame["time"].dt.tz_localize("America/New_York")
        with self.assertRaisesRegex(ValueError,"already be UTC"):
            study.validate_minutes(frame)


class ActualQuoteBoundTests(unittest.TestCase):
    def test_daily_exit_uses_observed_first_tick_not_minute_start(self):
        result,market,signal,end=outcome(fixture())
        self.assertEqual(result["reason"],"daily_flat_exit")
        self.assertEqual(study.engine.iso(result["exited"]),"2026-10-26T20:00:23")
        self.assertEqual(market.first_tradable_time[-1],result["exited"])
        self.assertEqual(result["swap_per_lot"],0)
        # The minute exists, but no quote existed yet at its :00 boundary.
        signal["time"]=pd.Timestamp("2026-10-26T19:00:00")
        rejected=market.outcome(signal,1,end)
        self.assertFalse(rejected["valid"])
        self.assertEqual(rejected["reason"],"no_observed_quote_at_entry_time")

    def test_intraminute_stop_uses_observed_last_tick_not_fabricated_59(self):
        frame=fixture();frame.loc[1,"low"]=97.0
        result,_,_,_=outcome(frame)
        self.assertEqual(result["reason"],"stop")
        self.assertEqual(study.engine.iso(result["exited"]),"2026-10-26T19:59:44")

    def test_delayed_close_across_wednesday_midnight_charges_static_funding(self):
        for direction,charge in ((1,-167.22),(-1,-128.457)):
            with self.subTest(direction=direction):
                result,_,_,_=outcome(fixture("2026-10-28",overnight=True),direction)
                self.assertEqual(result["reason"],"daily_flat_exit")
                self.assertEqual(study.engine.iso(result["exited"]),"2026-10-29T00:02:23")
                self.assertAlmostEqual(result["swap_per_lot"],charge,places=9)
                flags=study.holding_flags(result["entered"],result["exited"])
                self.assertTrue(flags["overnight"])
                self.assertTrue(flags["exit_past_daily_deadline_minute"])
                self.assertEqual(flags["crossed_utc_midnights"],1)

    def test_short_exit_uses_actual_ask(self):
        result,_,_,_=outcome(fixture(),direction=-1)
        self.assertEqual(result["exit_price"],100.1)


class MissingQuotePathTests(unittest.TestCase):
    @staticmethod
    def seconds(text):
        return int(pd.Timestamp(text).timestamp())

    def test_within_one_observed_minute_has_no_unobserved_minutes(self):
        minutes=np.array([self.seconds("2026-10-26T19:00")],dtype=np.int64)
        result=study.quote_path_observation(minutes,self.seconds("2026-10-26T19:00:17"),self.seconds("2026-10-26T19:00:44"))
        self.assertEqual(result,{"quote_minute_span":1,"observed_quote_minutes":1,
                                 "unobserved_quote_minutes":0,"max_unobserved_quote_gap_minutes":0})

    def test_three_absent_minutes_are_counted_without_interpolation(self):
        minutes=np.array([self.seconds("2026-10-26T19:00"),self.seconds("2026-10-26T19:04")],dtype=np.int64)
        result=study.quote_path_observation(minutes,minutes[0]+17,minutes[1]+23)
        self.assertEqual(result["quote_minute_span"],5)
        self.assertEqual(result["observed_quote_minutes"],2)
        self.assertEqual(result["unobserved_quote_minutes"],3)
        self.assertEqual(result["max_unobserved_quote_gap_minutes"],3)

    def test_weekend_absence_counts_and_is_not_classified_as_a_closure(self):
        minutes=np.array([self.seconds("2026-10-30T16:00"),self.seconds("2026-11-02T07:00")],dtype=np.int64)
        result=study.quote_path_observation(minutes,minutes[0]+17,minutes[1]+23)
        self.assertEqual(result["unobserved_quote_minutes"],3779)
        self.assertEqual(result["max_unobserved_quote_gap_minutes"],3779)
        self.assertEqual(set(result),{"quote_minute_span","observed_quote_minutes",
                                     "unobserved_quote_minutes","max_unobserved_quote_gap_minutes"})

    def test_sparse_coverage_diagnostics_leave_execution_and_records_unchanged(self):
        before,market,signal,end=outcome(fixture())
        diagnosis=study.quote_path_observation(market.times,before["entered"],before["exited"])
        self.assertGreater(diagnosis["unobserved_quote_minutes"],0)
        self.assertEqual(market.outcome(signal,1,end),before)
        record={"entry_time":study.engine.iso(before["entered"]),
                "exit_time":study.engine.iso(before["exited"]),"net_usd":-1.0,
                "funding_usd":0.0,"lots":0.01}
        original=dict(record)
        annotated=study.annotate_trade_observation([record],market.times)
        self.assertEqual(record,original)
        for key,value in original.items():self.assertEqual(annotated[0][key],value)
        self.assertEqual(annotated[0]["unobserved_quote_minutes"],diagnosis["unobserved_quote_minutes"])
        summary=study.holding_summary(annotated)
        self.assertEqual(summary["trades"],1)
        self.assertEqual(summary["trades_with_unobserved_quote_minutes"],1)

    def test_observation_failure_overrides_all_positive_numeric_gates(self):
        gates={"positive_return":True,"enough_trades":True,
               "all_available_direction_price_paths_observed":False}
        self.assertEqual(study.study_status(gates),"inconclusive_unobserved_price_paths")
        gates["all_available_direction_price_paths_observed"]=True
        self.assertEqual(study.study_status(gates),"historical_scenario_gates_passed_research_only")
        gates["positive_return"]=False
        self.assertEqual(study.study_status(gates),"edge_not_established")

    def test_finer_quotes_are_described_without_rounding_prices(self):
        frame=fixture();frame.loc[0,"ask_open"]=100.101
        frame=study.validate_minutes(frame);original=frame.copy(deep=True)
        report=study.quote_grid_diagnostics(frame,SPECS)
        self.assertEqual(report["OHLC_cells_off_protective_grid"],1)
        self.assertEqual(report["minutes_with_any_quote_off_protective_grid"],1)
        self.assertAlmostEqual(report["maximum_price_distance_to_protective_grid"],.001,places=10)
        pd.testing.assert_frame_equal(frame,original)
        self.assertEqual(frame.loc[0,"ask_open"],100.101)


class PlanIdentityTests(unittest.TestCase):
    def plan(self):
        return {"variants":list(study.VARIANTS),"primary":"operations_only","secondary":"regime_retest",
                "scenario_clock":"UTC","optimization_permitted":False,"virtual_contract":dict(SPECS),
                "evaluation_start_inclusive":"2023-01-01","evaluation_end_exclusive":"2024-01-01",
                "warmup_start_inclusive":"2022-10-01",
                "signal_module_sha256":study.sha256_file(study.MODULE_DIR/"gold_signals.py"),
                "execution_module_sha256":study.sha256_file(study.MODULE_DIR/"benchmark_revision.py")}

    def test_plan_rejects_changed_sibling_module_identity(self):
        plan=self.plan();plan["signal_module_sha256"]="0"*64
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"plan.json";path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError,"module hash mismatch"):
                study.load_plan(path)

    def test_plan_accepts_the_bound_unmodified_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"plan.json";path.write_text(json.dumps(self.plan()))
            plan,hashes=study.load_plan(path)
        self.assertEqual(plan["primary"],"operations_only")
        self.assertEqual(set(hashes),{"gold_signals.py","benchmark_revision.py"})


if __name__=="__main__":unittest.main()
