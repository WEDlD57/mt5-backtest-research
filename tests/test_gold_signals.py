import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"analysis"))
"""Indicator and closed-bar causality checks for the independent signal module."""
import unittest
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from gold_signals import FrozenRules,generate_signals,hourly_bars,mt5_indicators,read_minutes


def synthetic_minutes():
    times=pd.date_range('2026-01-01',periods=400,freq='h')
    frame=pd.DataFrame({'time':times,'open':10.0,'high':10.1,'low':9.9,'close':10.0,'ask_open':10.01})
    frame.loc[frame.time==pd.Timestamp('2026-01-12T07:00'),['open','high','low','close','ask_open']]=[10.0,11.0,9.99,10.8,10.01]
    frame.loc[frame.time==pd.Timestamp('2026-01-12T08:00'),['open','high','low','close','ask_open']]=[10.8,10.9,10.1,10.6,10.81]
    return frame


class IndicatorAndSignalTests(unittest.TestCase):
    def test_atr_is_rolling_sma_and_ema_has_price_seed(self):
        bars=pd.DataFrame({'close':[10.,11.,10.,12.,11.], 'high':[11.,12.,13.,14.,12.], 'low':[9.,10.,9.,11.,10.]})
        rules=FrozenRules(ema_period=3,atr_period=2,adx_period=3)
        actual=mt5_indicators(bars,rules)
        np.testing.assert_array_equal(actual.ATR.to_numpy(),[0.,0.,3.,4.,3.])
        np.testing.assert_array_equal(actual.ema.to_numpy(),[10.,10.5,10.25,11.125,11.0625])
        # Per-bar normalized DM is EMA-smoothed, including a tied-DM zero.
        np.testing.assert_allclose(actual.ADX.to_numpy(),[0.,50.,75.,87.5,66.47727272727273],rtol=0,atol=1e-12)

    def test_retest_cannot_enter_on_breakout_candle(self):
        minutes=synthetic_minutes()
        ops,_=generate_signals(minutes,'2026-01-12','2026-01-13','operations_only')
        retest,_=generate_signals(minutes,'2026-01-12','2026-01-13','regime_retest')
        self.assertEqual(ops.time.tolist(),[pd.Timestamp('2026-01-12T08:00')])
        self.assertEqual(retest.time.tolist(),[pd.Timestamp('2026-01-12T09:00')])
        self.assertEqual(retest.armed_age.tolist(),[1])
        self.assertEqual(retest.armed_level.tolist(),[10.1])
        self.assertGreaterEqual(retest.ADX.iloc[0],18)

    def test_future_bars_do_not_change_earlier_signals(self):
        original=synthetic_minutes();changed=original.copy()
        future=changed.time>pd.Timestamp('2026-01-12T09:00')
        changed.loc[future,['open','high','low','close','ask_open']]=[200.,201.,199.,200.,200.01]
        for variant in ['operations_only','regime_retest']:
            a,_=generate_signals(original,'2026-01-12','2026-01-13',variant)
            b,_=generate_signals(changed,'2026-01-12','2026-01-13',variant)
            a=a[a.time<=pd.Timestamp('2026-01-12T09:00')].reset_index(drop=True)
            b=b[b.time<=pd.Timestamp('2026-01-12T09:00')].reset_index(drop=True)
            pd.testing.assert_frame_equal(a,b,check_exact=True)

    def test_current_bar_high_low_close_are_not_used_for_entry_signal(self):
        original=synthetic_minutes();changed=original.copy()
        current=changed.time==pd.Timestamp('2026-01-12T09:00')
        changed.loc[current,['high','low','close']]=[100.,1.,99.]
        a,_=generate_signals(original,'2026-01-12','2026-01-13','regime_retest')
        b,_=generate_signals(changed,'2026-01-12','2026-01-13','regime_retest')
        a=a[a.time==pd.Timestamp('2026-01-12T09:00')].reset_index(drop=True)
        b=b[b.time==pd.Timestamp('2026-01-12T09:00')].reset_index(drop=True)
        pd.testing.assert_frame_equal(a,b,check_exact=True)

    def test_actual_first_tick_must_be_present_and_inside_minute(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'minutes.csv'
            row={'time':'2023-01-02T07:00:00Z','open':10.,'high':10.1,'low':9.9,'close':10.,'ask_open':10.01}
            for first_tick,message in [('','Missing first-tick'),('2023-01-02T07:01:00Z','outside its minute')]:
                pd.DataFrame([{**row,'first_tick_time_utc':first_tick}]).to_csv(path,index=False)
                with self.assertRaisesRegex(ValueError,message):read_minutes(path)
            pd.DataFrame([{**row,'first_tick_time_utc':'2023-01-02T07:00:02.500Z'}]).to_csv(path,index=False)
            result=read_minutes(path)
            self.assertEqual(result.first_tick_time.iloc[0],pd.Timestamp('2023-01-02T07:00:02'))

    def test_first_existing_minute_and_actual_first_tick_are_honored(self):
        minutes=synthetic_minutes()
        minutes.loc[minutes.time==pd.Timestamp('2026-01-12T09:00'),'time']=pd.Timestamp('2026-01-12T09:03')
        without_ticks,_=generate_signals(minutes,'2026-01-12','2026-01-13','regime_retest')
        self.assertEqual(without_ticks.time.tolist(),[pd.Timestamp('2026-01-12T09:03')])
        minutes['first_tick_time']=minutes.time+pd.Timedelta(seconds=2)
        with_ticks,meta=generate_signals(minutes,'2026-01-12','2026-01-13','regime_retest')
        self.assertEqual(with_ticks.time.tolist(),[pd.Timestamp('2026-01-12T09:03:02')])
        self.assertTrue(meta['first_tick_second_known'])

    def test_unvalidated_intraday_start_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"whole feed dates"):
            generate_signals(synthetic_minutes(),'2026-01-12T07:00','2026-01-13','operations_only')

    def test_empty_hours_are_not_forward_filled(self):
        minutes=synthetic_minutes()
        subset=minutes[minutes.time.isin(pd.to_datetime(['2026-01-12T07:00','2026-01-12T10:00']))]
        bars=hourly_bars(subset)
        self.assertEqual(bars.bar_time.tolist(),pd.to_datetime(['2026-01-12T07:00','2026-01-12T10:00']).tolist())
        self.assertEqual(len(bars),2)


if __name__=='__main__':unittest.main()
