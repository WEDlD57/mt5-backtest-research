"""Closed-bar signal replication of the frozen tester-only gold revision.

No order execution, profit calculation, fitting, or live terminal connection.
Times are used in the supplied feed's time basis. UTC timestamps are converted
only to UTC-naive form; this module never infers a broker offset. Evaluations
are placed at the first available M1 timestamp in each new H1 bar unless a
validated first_tick_time[_utc] column provides the actual first tick. Legacy
M1 data do not expose that second; their comparison to native events normalizes
to minute precision and records second-level differences separately.

Indicator formulas follow the installed MetaQuotes Examples/ATR.mq5,
Examples/ADX.mq5 and Examples/Custom Moving Average.mq5 (build 6231).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FrozenRules:
    breakout_bars: int = 24
    ema_period: int = 200
    atr_period: int = 14
    adx_period: int = 14
    min_adx: float = 18.0
    retest_bars: int = 3
    retest_tolerance_atr: float = 0.25
    retest_close_buffer_atr: float = 0.02


RULES = FrozenRules()
FIELDS = ["time", "bar_time", "dir", "ATR", "ema", "entrybid", "ask", "ADX",
          "armed_level", "armed_age", "regime_retest_enabled"]
VARIANTS = ("operations_only", "regime_retest")


def read_minutes(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, float_precision="round_trip")
    if "time" not in frame:
        raise ValueError("Minute input requires a time column")
    if frame.empty:
        raise ValueError("Minute input contains no bars")
    frame["time"] = pd.to_datetime(frame["time"], format="mixed", errors="raise")
    if frame["time"].dt.tz is not None:
        if str(frame["time"].dt.tz) != "UTC":
            raise ValueError("Input timezone must be naive feed time or explicit UTC; no broker offset is inferred")
        frame["time"] = frame["time"].dt.tz_localize(None)
    tick_column = "first_tick_time" if "first_tick_time" in frame else "first_tick_time_utc" if "first_tick_time_utc" in frame else None
    if tick_column:
        first_ticks = pd.to_datetime(frame[tick_column], format="mixed", errors="raise")
        if first_ticks.dt.tz is not None:
            if str(first_ticks.dt.tz) != "UTC":
                raise ValueError("First-tick timezone must be naive feed time or explicit UTC")
            first_ticks = first_ticks.dt.tz_localize(None)
        if first_ticks.isna().any():
            raise ValueError("Missing first-tick timestamp")
        if ((first_ticks < frame["time"]) | (first_ticks >= frame["time"] + pd.Timedelta(minutes=1))).any():
            raise ValueError("First-tick timestamp is outside its minute")
        # MQL datetime/TimeCurrent logs have second precision.
        frame["first_tick_time"] = first_ticks.dt.floor("s")
    numeric = ["open", "high", "low", "close"]
    if not set(numeric).issubset(frame):
        raise ValueError("Minute input requires bid open/high/low/close")
    values = frame[numeric].to_numpy(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("Missing, nonfinite or nonpositive bid prices")
    if frame["time"].duplicated().any() or not frame["time"].is_monotonic_increasing:
        raise ValueError("Minute timestamps must be unique and chronological")
    if (frame["time"] != frame["time"].dt.floor("min")).any():
        raise ValueError("Minute timestamps must be minute boundaries")
    if (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any() or (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError("Inconsistent bid OHLC")
    if "ask_open" in frame:
        ask = frame["ask_open"].to_numpy(float)
        if not np.isfinite(ask).all() or (ask <= 0).any() or (ask < frame["open"].to_numpy(float)).any():
            raise ValueError("Invalid ask openings")
    return frame


def hourly_bars(minutes: pd.DataFrame) -> pd.DataFrame:
    """Aggregate only existing hours; do not manufacture bars across gaps."""
    work = minutes.copy()
    work["bar_time"] = work["time"].dt.floor("h")
    work["entrybid"] = work["open"]
    work["evaluation_tick_time"] = work["first_tick_time"] if "first_tick_time" in work else work["time"]
    if "ask_open" not in work:
        work["ask_open"] = np.nan
    groups = work.groupby("bar_time", sort=True, observed=True)
    bars = groups.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                      close=("close", "last"), evaluation_time=("evaluation_tick_time", "first"),
                      entrybid=("entrybid", "first"), ask=("ask_open", "first"),
                      minute_count=("time", "size")).reset_index()
    return bars


def mt5_indicators(bars: pd.DataFrame, rules: FrozenRules = RULES) -> pd.DataFrame:
    """Replicate MetaQuotes indicator arithmetic, including its EMA-based iADX."""
    close = bars["close"].to_numpy(float)
    high = bars["high"].to_numpy(float)
    low = bars["low"].to_numpy(float)
    n = len(bars)
    ema = np.zeros(n); tr = np.zeros(n); atr = np.zeros(n)
    pdi = np.zeros(n); ndi = np.zeros(n); adx = np.zeros(n)
    if not n:
        return pd.DataFrame({"ema": ema, "ATR": atr, "ADX": adx})
    ema[0] = close[0]
    ema_factor = 2.0 / (rules.ema_period + 1.0)
    adx_factor = 2.0 / (rules.adx_period + 1.0)
    for i in range(1, n):
        ema[i] = close[i] * ema_factor + ema[i - 1] * (1.0 - ema_factor)
        tr[i] = max(high[i], close[i - 1]) - min(low[i], close[i - 1])
        positive = max(high[i] - high[i - 1], 0.0)
        negative = max(low[i - 1] - low[i], 0.0)
        if positive > negative:
            negative = 0.0
        elif positive < negative:
            positive = 0.0
        else:
            positive = negative = 0.0
        # ADX.mq5 normalizes DM by each bar's TR before EMA smoothing.
        adx_tr = max(abs(high[i] - low[i]), abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
        raw_positive = 100.0 * positive / adx_tr if adx_tr else 0.0
        raw_negative = 100.0 * negative / adx_tr if adx_tr else 0.0
        pdi[i] = raw_positive * adx_factor + pdi[i - 1] * (1.0 - adx_factor)
        ndi[i] = raw_negative * adx_factor + ndi[i - 1] * (1.0 - adx_factor)
        denominator = pdi[i] + ndi[i]
        dx = 100.0 * abs((pdi[i] - ndi[i]) / denominator) if denominator else 0.0
        adx[i] = dx * adx_factor + adx[i - 1] * (1.0 - adx_factor)
    if n > rules.atr_period:
        first = 0.0
        for i in range(1, rules.atr_period + 1):
            first += tr[i]
        atr[rules.atr_period] = first / rules.atr_period
        for i in range(rules.atr_period + 1, n):
            atr[i] = atr[i - 1] + (tr[i] - tr[i - rules.atr_period]) / rules.atr_period
    return pd.DataFrame({"ema": ema, "ATR": atr, "ADX": adx})


def load_sessions(path: Path | None) -> list[tuple[int, int, int]] | None:
    if path is None:
        return None
    frame = pd.read_csv(path)
    return [(int(r.day), int(r.from_seconds), int(r.to_seconds)) for r in frame.itertuples()]


def broker_session_open(time: pd.Timestamp, sessions: list[tuple[int, int, int]] | None) -> bool:
    if sessions is None:
        return True
    day = (time.dayofweek + 1) % 7
    seconds = time.hour * 3600 + time.minute * 60 + time.second
    for session_day, begin, end in sessions:
        if begin == end and day == session_day:
            return True
        if begin < end and day == session_day and begin <= seconds < end:
            return True
        if begin > end and ((day == session_day and seconds >= begin) or (day == (session_day + 1) % 7 and seconds < end)):
            return True
    return False


def entry_window_open(time: pd.Timestamp, sessions: list[tuple[int, int, int]] | None) -> bool:
    if time.dayofweek >= 5:
        return False
    seconds = time.hour * 3600 + time.minute * 60 + time.second
    deadline = (17 if time.dayofweek == 4 else 20) * 3600
    return 7 * 3600 <= seconds < deadline - 1800 and broker_session_open(time, sessions)


def generate_signals(minutes: pd.DataFrame, start: str, end: str, variant: str,
                     sessions: list[tuple[int, int, int]] | None = None,
                     rules: FrozenRules = RULES) -> tuple[pd.DataFrame, dict[str, Any]]:
    if variant not in VARIANTS:
        raise ValueError("Unknown frozen variant")
    start_time, end_time = pd.Timestamp(start), pd.Timestamp(end)
    if start_time >= end_time:
        raise ValueError("Start must precede end")
    if start_time != start_time.normalize() or end_time != end_time.normalize():
        raise ValueError("Validated evaluation windows use whole feed dates at midnight")
    # Retain all supplied earlier bars for indicator initialization. No future
    # data enter any decision: every signal accesses only completed bars.
    bars = hourly_bars(minutes)
    indicators = mt5_indicators(bars, rules)
    times = pd.DatetimeIndex(bars["bar_time"])
    evaluations = pd.DatetimeIndex(bars["evaluation_time"])
    first = int(times.searchsorted(start_time.floor("h")))
    # OnInit sets g_lastBar to the current bar and suppresses its first tick.
    first = min(first + 1, len(bars))
    arm_direction = 0; arm_level = 0.0; arm_index = -1
    counters = {"bars": 0, "outside_entry_window": 0, "warmup": 0,
                "raw_breakouts": 0, "armed": 0, "expired": 0,
                "regime_rejected": 0, "signal_opportunities": 0}
    signals = []
    regime_retest = variant == "regime_retest"
    for i in range(first, len(bars)):
        now = evaluations[i]
        if now >= end_time:
            break
        if now < start_time:
            continue
        counters["bars"] += 1
        if not entry_window_open(now, sessions):
            arm_direction = 0; arm_level = 0.0; arm_index = -1
            counters["outside_entry_window"] += 1
            continue
        if i + 1 < max(rules.ema_period + 2, rules.atr_period + 2) or i < rules.breakout_bars + 1:
            counters["warmup"] += 1
            continue
        j = i - 1
        atr = float(indicators.iloc[j]["ATR"])
        ema = float(indicators.iloc[j]["ema"])
        adx = float(indicators.iloc[j]["ADX"]) if regime_retest else 0.0
        prior_adx = float(indicators.iloc[j - 1]["ADX"]) if regime_retest else 0.0
        highest = float(bars.iloc[i - rules.breakout_bars - 1:i - 1]["high"].max())
        lowest = float(bars.iloc[i - rules.breakout_bars - 1:i - 1]["low"].min())
        closed = bars.iloc[j]
        close = float(closed["close"])
        breakout = 1 if close > highest and close > ema else -1 if close < lowest and close < ema else 0
        if breakout:
            counters["raw_breakouts"] += 1
        direction = 0; used_level = 0.0; used_age = 0
        if not regime_retest:
            direction = breakout
        else:
            if arm_direction and j > arm_index:
                age = j - arm_index
                if age <= rules.retest_bars:
                    touch = abs(float(closed["low" if arm_direction > 0 else "high"]) - arm_level) <= rules.retest_tolerance_atr * atr
                    beyond = close > arm_level + rules.retest_close_buffer_atr * atr if arm_direction > 0 else close < arm_level - rules.retest_close_buffer_atr * atr
                    trend = close > ema if arm_direction > 0 else close < ema
                    regime = adx >= rules.min_adx and adx >= prior_adx
                    if touch and beyond and trend and regime:
                        direction = arm_direction; used_level = arm_level; used_age = age
                        arm_direction = 0; arm_level = 0.0; arm_index = -1
                    elif touch and beyond and (not trend or not regime):
                        counters["regime_rejected"] += 1
                if not direction and age >= rules.retest_bars:
                    arm_direction = 0; arm_level = 0.0; arm_index = -1
                    counters["expired"] += 1
            if not direction and breakout and (not arm_direction or breakout != arm_direction):
                arm_direction = breakout; arm_level = highest if breakout > 0 else lowest; arm_index = j
                counters["armed"] += 1
        if not direction:
            continue
        counters["signal_opportunities"] += 1
        signals.append({"time": now, "bar_time": times[i], "dir": direction,
                        "ATR": atr, "ema": ema, "entrybid": float(bars.iloc[i]["entrybid"]),
                        "ask": float(bars.iloc[i]["ask"]), "ADX": adx,
                        "armed_level": used_level, "armed_age": used_age,
                        "regime_retest_enabled": int(regime_retest)})
    result = pd.DataFrame(signals, columns=FIELDS)
    metadata = {"variant": variant, "start_inclusive": start_time.isoformat(),
                "end_exclusive": end_time.isoformat(), "rules": asdict(rules),
                "indicator_history_first_bar": times[0].isoformat() if len(times) else None,
                "total_hourly_bars": len(times), "diagnostics": counters,
                "first_tick_second_known": "first_tick_time" in minutes,
                "time_basis": "Input feed timestamps; no broker offset inferred",
                "ask_open_available": "ask_open" in minutes,
                "method": "MetaQuotes EMA200, rolling-SMA ATR14, EMA-smoothed normalized-DM iADX14; closed candles only."}
    return result, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bid-m1", type=Path, required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--variant", choices=VARIANTS, required=True)
    parser.add_argument("--sessions", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    minutes = read_minutes(args.bid_m1)
    signals, meta = generate_signals(minutes, args.start, args.end, args.variant, load_sessions(args.sessions))
    meta["input_sha256"] = hashlib.sha256(args.bid_m1.read_bytes()).hexdigest()
    meta["module_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if args.sessions:
        meta["session_file_sha256"] = hashlib.sha256(args.sessions.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    signals.to_csv(args.out, index=False, date_format="%Y.%m.%d %H:%M:%S")
    args.out.with_suffix(".json").write_text(json.dumps(meta, indent=2, allow_nan=False) + "\n")
    print(json.dumps(meta, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
