"""Synthetic execution checks for the exploratory daily-flat benchmark.

Run: python -m unittest discover -s work/revision -p test_benchmark_revision.py -v
"""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
import pandas as pd
from benchmark_revision import Market, iso


def fixture(day="2026-10-26", deadline_hour=20, closed_at_deadline=False):
    times = pd.to_datetime([day+f" {deadline_hour-1}:00:00", day+f" {deadline_hour-1}:59:00",
                            day+f" {deadline_hour}:00:00", day+f" {deadline_hour}:02:00"])
    frame = pd.DataFrame({"time": times, "open": [100.0]*4, "high": [100.2]*4,
                           "low": [99.8]*4, "close": [100.0]*4, "spread": [10]*4,
                           "ask_open": [100.1]*4, "ask_high": [100.3]*4,
                           "ask_low": [99.9]*4, "ask_close": [100.1]*4,
                           "last_tick_time": times+pd.Timedelta(seconds=59)})
    specs = {"point":"0.01", "digits":"2", "tick_size":"0.01", "contract_size":"100",
             "volume_min":"0.01", "volume_max":"100", "volume_step":"0.01",
             "currency_profit":"USD", "account_currency":"USD", "swap_mode":"0",
             "swap_long":"0", "swap_short":"0"}
    day_number=(int(times[0].timestamp())//86400+4)%7
    sessions = None
    if closed_at_deadline:
        sessions = pd.DataFrame([{"day":day_number,"from_seconds":0,"to_seconds":deadline_hour*3600},
                                  {"day":day_number,"from_seconds":deadline_hour*3600+120,"to_seconds":86400}])
    signal=pd.Series({"time":times[0], "entrybid":100.0, "ask":100.1, "ATR":1.0})
    return frame,specs,sessions,signal,int((times[-1]+pd.Timedelta(hours=1)).timestamp())


class DailyFlatExecutionTests(unittest.TestCase):
    def outcome(self, direction=1, **kwargs):
        frame,specs,sessions,signal,end=fixture(**kwargs)
        return Market(frame,specs,None,sessions=sessions).outcome(signal,direction,end)

    def test_long_flat_at_monday_twenty(self):
        result=self.outcome()
        self.assertEqual(result["reason"],"daily_flat_exit")
        self.assertEqual(iso(result["exited"]),"2026-10-26T20:00:00")
        self.assertEqual(result["swap_per_lot"],0)

    def test_short_uses_ask_for_flat(self):
        result=self.outcome(direction=-1)
        self.assertEqual(result["reason"],"daily_flat_exit")
        self.assertEqual(result["exit_price"],100.1)
        self.assertEqual(iso(result["exited"]),"2026-10-26T20:00:00")

    def test_friday_flat_at_seventeen(self):
        result=self.outcome(day="2026-10-23",deadline_hour=17)
        self.assertEqual(iso(result["exited"]),"2026-10-23T17:00:00")

    def test_closed_deadline_waits_for_next_tradable_quote(self):
        result=self.outcome(closed_at_deadline=True)
        self.assertEqual(result["reason"],"daily_flat_exit")
        self.assertEqual(iso(result["exited"]),"2026-10-26T20:02:00")

    def test_stop_before_flat_is_honored(self):
        frame,specs,sessions,signal,end=fixture()
        frame.loc[1,"low"]=97.0
        result=Market(frame,specs,None,sessions=sessions).outcome(signal,1,end)
        self.assertEqual(result["reason"],"stop")
        self.assertLess(result["exited"],int(pd.Timestamp("2026-10-26T20:00").timestamp()))

    def test_stop_gap_on_flat_open_has_priority(self):
        frame,specs,sessions,signal,end=fixture()
        frame.loc[2,["open","high","low","close"]]=[97.0,97.1,96.9,97.0]
        result=Market(frame,specs,None,sessions=sessions).outcome(signal,1,end)
        self.assertEqual(result["reason"],"stop_at_time_exit_open")
        self.assertEqual(result["exit_price"],97.0)

    def test_entry_after_cutoff_is_rejected(self):
        frame,specs,sessions,signal,end=fixture()
        signal["time"]=pd.Timestamp("2026-10-26T20:00")
        result=Market(frame,specs,None,sessions=sessions).outcome(signal,1,end)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"],"outside_entry_window")


if __name__ == "__main__":
    unittest.main()
